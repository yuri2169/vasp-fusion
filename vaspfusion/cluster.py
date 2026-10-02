"""Cluster labels on Bitcoin: an address spent together with a labelled exchange address
belongs to that exchange.

Every input of a transaction is signed by its owner, so addresses that appear together
as inputs of one transaction are controlled by one party (common-input ownership;
Meiklejohn et al., IMC 2013). An exchange sweeps its customers' deposit addresses into
its own wallets in exactly such transactions, so a deposit address that no list names
is still tied to the exchange by the labelled addresses it was swept with.

What is used, and what is not:

* `graph/resolve.py` on the address's own page of transactions, with the CoinJoin guard
  (`graph/coinjoin.py`): a CoinJoin's inputs belong to different people.
* NOT the change heuristic. "This output has never been seen before, so it is the
  sender's change" cannot be checked from one address's page, and when it is wrong it
  puts an exchange's label on the exchange's customer. Only co-spending carries a label.
* A cluster whose labelled members name two owners, or an owner that is not a VASP,
  gives no label (and a note). Nothing is settled by picking a side.

The label is `derived`: its confidence is the weight of the strongest labelled member
times CO_SPEND (hand-set, not calibrated), and its evidence says how many addresses the
cluster has, how many are labelled, and which transaction links them.

`ClusterLabels` wraps the label store for a Bitcoin trace. `lookup_many` is the store's
(plus names for the two things that are not addresses: a CoinJoin sink and newly mined
coins). `infer` is the cluster step; the trace calls it for the traced wallet and for
each unlabelled wallet that holds enough of the funds to matter (trace.py).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from .chains.base import InvalidAddress, ProviderError
from .chains.btc import COINBASE, COINJOIN_SINK, UtxoTx, coinjoin_ids, tx_frame
from .explain import fmt
from .graph.resolve import resolve_entities
from .labels.lookup import Label
from .labels.normalize import VASP_CATEGORIES

CLUSTER_SOURCE = "vaspfusion-cluster"
CO_SPEND = 0.90         # weight of "spent together with a labelled address" (hand-set)
PAGES = 1               # pages of the address's history read for its cluster


@dataclass(frozen=True)
class Cluster:
    address: str
    members: tuple[str, ...]        # the address and everything co-spent with it, sorted
    links: tuple[str, ...]          # transactions in which it was co-spent, oldest first
    coinjoin_skipped: int           # CoinJoin-shaped transactions left out of the clustering


def cluster_of(address: str, txs: list[UtxoTx]) -> Cluster:
    """The addresses that share an owner with `address`, by co-spending in `txs`."""
    if not txs:
        return Cluster(address, (address,), (), 0)
    mapping, stats = resolve_entities(tx_frame(txs), change=False, coinjoin=coinjoin_ids(txs))
    owner = dict(zip(mapping["address"].to_list(), mapping["entity_id"].to_list()))
    mine = owner.get(address)
    members = tuple(sorted(a for a, e in owner.items() if e == mine)) if mine else (address,)
    inside = set(members)
    links = tuple(t.txid for t in sorted(txs, key=lambda t: (t.time, t.txid))
                  if address in t.input_addresses and len(inside & set(t.input_addresses)) > 1)
    return Cluster(address, members, links if len(members) > 1 else (),
                   stats.get("coinjoin_txs_skipped", 0))


def _weight(label: Label) -> float:
    from .attribute.rules import label_weight
    return label_weight(label)


def _coinjoin_label(address: str, chain: str, tx: UtxoTx | None) -> Label:
    txid = address[len(COINJOIN_SINK):]
    shape = ""
    if tx is not None:
        value, equal = Counter(v for a, v in tx.outputs if a).most_common(1)[0]
        shape = (f": {len(tx.input_addresses)} input addresses, and {equal} of its "
                 f"{sum(1 for a, _ in tx.outputs if a)} outputs are "
                 f"{fmt.amount(Decimal(value).scaleb(-8), 'BTC')} each")
    return Label(address, chain, "CoinJoin", "mixer", "unknown", "derived", "vaspfusion-coinjoin",
                 None, "CoinJoin-shaped transaction", None,
                 f"Transaction {txid} has the shape of a collaborative CoinJoin{shape}. Several "
                 "owners put coins in and took equal amounts out, so which output is whose "
                 "cannot be told and the trace stops here. The shape is a rule, not a proof.")


class ClusterLabels:
    def __init__(self, store, provider, pages: int = PAGES):
        self.store, self.provider, self.pages = store, provider, pages
        self.notes: list[str] = []
        self._inferred: dict[str, Label | None] = {}

    # -------------------------------------------------------------- direct labels
    def lookup_many(self, pairs):
        pairs = list(pairs)
        found = dict(self.store.lookup_many(pairs))
        for address, chain in pairs:
            if address.startswith(COINJOIN_SINK):
                seen = getattr(self.provider, "_seen", {})
                found[(address, chain)] = _coinjoin_label(
                    address, chain, seen.get(address[len(COINJOIN_SINK):]))
            elif address == COINBASE:
                found[(address, chain)] = Label(
                    address, chain, "Newly mined coins", "entity", "unknown", "derived",
                    "vaspfusion-coinbase", None, "Block reward (coinbase)", None,
                    "These coins were created by the block that paid them out; they have no "
                    "sender.")
        return found

    # -------------------------------------------------------------- the cluster step
    def infer(self, address: str, chain: str) -> Label | None:
        if chain != "bitcoin" or address == COINBASE or address.startswith(COINJOIN_SINK):
            return None
        if address not in self._inferred:
            self._inferred[address] = self._infer(address, chain)
        return self._inferred[address]

    def _note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    def _infer(self, address: str, chain: str) -> Label | None:
        try:
            txs, whole = self.provider.txs(address, self.pages)
        except (ProviderError, InvalidAddress) as e:
            self._note(f"The transactions of {fmt.short(address)} could not be read, so its "
                       f"wallet cluster was not checked ({e}).")
            return None
        cluster = cluster_of(address, txs)
        others = [m for m in cluster.members if m != address]
        if not others:
            return None
        found = self.store.lookup_many([(m, chain) for m in others])
        if not found:
            return None
        owners = sorted({lab.entity for lab in found.values()})
        if len(owners) > 1:
            self._note(f"{fmt.short(address)} was spent together with addresses labelled "
                       f"{' and '.join(owners)}: two owners in one cluster, so no label was "
                       "derived from it.")
            return None
        best = max(found.values(), key=lambda lab: (_weight(lab), lab.address))
        if best.category not in VASP_CATEGORIES:
            return None
        return self._label(address, chain, cluster, found, best, len(txs), whole)

    def _label(self, address: str, chain: str, cluster: Cluster, found: dict, best: Label,
               n_txs: int, whole: bool) -> Label:
        n, m = len(cluster.members), len(found)
        confidence = round(_weight(best) * CO_SPEND, 4)
        seen = getattr(self.provider, "_seen", {})
        # the transaction that has both this address and the labelled one among its inputs
        shared = [t for t in cluster.links
                  if t in seen and best.address in seen[t].input_addresses] or cluster.links
        said = f" (\"{best.label}\")" if best.label else ""
        evidence = (
            f"Wallet cluster: cluster of {n} addresses, {m} labelled {best.entity}. "
            f"{fmt.short(address)} was spent together with {n - 1} other "
            f"address{'es' if n != 2 else ''} in {len(cluster.links)} "
            f"transaction{'s' if len(cluster.links) != 1 else ''} (the inputs of one "
            "transaction are signed by one owner; CoinJoin-shaped transactions are left out). "
            f"Labelled member: {best.address}{said}, {fmt.tier_words(best.tier)}, source "
            f"{best.source}. Linking transaction: {shared[0]}. Rule confidence "
            f"{confidence:.2f} = {_weight(best):.2f} (that label) x {CO_SPEND:.2f} (spent "
            f"together), hand-set, not calibrated. Read from the {n_txs} "
            f"{'' if whole else 'most recent '}transaction{'s' if n_txs != 1 else ''} of the "
            f"address{'' if whole else '; it has more'}.")
        return Label(address=address, chain=chain, entity=best.entity, category=best.category,
                     kind="deposit", tier="derived", source=CLUSTER_SOURCE, source_url=None,
                     label=f"{best.entity} wallet (derived: spent together with {m} labelled "
                           f"{best.entity} address{'es' if m != 1 else ''})",
                     confidence=confidence, evidence=evidence)


def cluster_labels(chain: str, labels, provider):
    """`labels` as a Bitcoin trace needs them; unchanged for every other chain."""
    return ClusterLabels(labels, provider) if chain == "bitcoin" else labels
