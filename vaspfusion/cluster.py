"""Cluster labels on Bitcoin: an address spent together with a labelled exchange address
belongs to that exchange.

Every input of a transaction is signed by its owner, so addresses that appear together
as inputs of one transaction are controlled by one party (common-input ownership;
Meiklejohn et al., IMC 2013). An exchange sweeps its customers' deposit addresses into
its own wallets in exactly such transactions, so a deposit address that no list names
is still tied to the exchange by the labelled addresses it was swept with.

What is used, and what is not:

* `graph/resolve.py` on the address's own page of transactions, without the
  transactions whose inputs are several people's by their shape: a CoinJoin
  (`chains.btc.coinjoin_ids`) and any other joint payment (`chains.btc.join_like`).
* NOT the change heuristic. "This output has never been seen before, so it is the
  sender's change" cannot be checked from one address's page, and when it is wrong it
  puts an exchange's label on the exchange's customer. Only co-spending carries a label.
* A label needs a labelled address that was spent WITH this address, in one
  transaction that can be named. A labelled address that is only in the same cluster
  through other addresses is counted ("M labelled") but does not carry the label.
* A cluster whose labelled members name two owners, or an owner that is not a VASP, or
  no owner at all (an "exchange" tag with no name), gives no label, and a note says
  why. Nothing is settled by picking a side.

The label is `derived`, kind `unknown`: co-spending shows the exchange controls the
address, not whether it is a customer's deposit address or one of the exchange's own
wallets. Its confidence is the weight of the strongest labelled address it was spent
with, times CO_SPEND (hand-set, not calibrated). Its evidence says how many addresses
the cluster has, how many are labelled, and which transaction links them.

`ClusterLabels` wraps the label store for a Bitcoin trace. `lookup_many` is the store's.
`infer` is the cluster step; the trace calls it for the traced wallet and for each
unlabelled wallet that holds enough of the funds to matter (trace.py).
"""
from __future__ import annotations

from dataclasses import dataclass

from .chains.base import InvalidAddress, ProviderError
from .chains.btc import UtxoTx, coinjoin_ids, join_like, tx_frame
from .explain import fmt
from .graph.resolve import resolve_entities
from .labels.lookup import Label
from .labels.normalize import VASP_CATEGORIES

CLUSTER_SOURCE = "vaspfusion-cluster"
CLUSTER_MARK = "derived: spent together with"   # in the `label` of every cluster label
CO_SPEND = 0.90         # weight of "spent together with a labelled address" (hand-set)
PAGES = 1               # pages of the address's history read for its cluster
NO_OWNER = "Unidentified exchange"      # labels.normalize: a tag that names nobody


@dataclass(frozen=True)
class Cluster:
    address: str
    members: tuple[str, ...]            # the address and every address of its owner, sorted
    direct: dict[str, tuple[str, ...]]  # addresses spent WITH it -> the transactions, oldest first
    links: tuple[str, ...]              # transactions in which it was spent with others
    left_out: int                       # joint-payment-shaped transactions not used


def cluster_of(address: str, txs: list[UtxoTx]) -> Cluster:
    """The addresses that share an owner with `address`, by co-spending in `txs`."""
    if not txs:
        return Cluster(address, (address,), {}, (), 0)
    joint = coinjoin_ids(txs) | {t.txid for t in txs if join_like(t)}
    mapping, _ = resolve_entities(tx_frame(txs), change=False, coinjoin=joint)
    owner = dict(zip(mapping["address"].to_list(), mapping["entity_id"].to_list()))
    mine = owner.get(address)
    members = tuple(sorted(a for a, e in owner.items() if e == mine)) if mine else (address,)
    direct: dict[str, list[str]] = {}
    links, left_out = [], 0
    for t in sorted({t.txid: t for t in txs}.values(), key=lambda t: (t.time, t.txid)):
        others = [a for a in t.input_addresses if a != address]
        if address not in t.input_addresses or not others:
            continue
        if t.txid in joint:
            left_out += 1
            continue
        links.append(t.txid)
        for a in others:
            direct.setdefault(a, []).append(t.txid)
    return Cluster(address, members, {a: tuple(v) for a, v in direct.items()}, tuple(links),
                   left_out)


def _weight(label: Label) -> float:
    from .attribute.rules import label_weight
    return label_weight(label)


def _plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else many or word + 's'}"


class ClusterLabels:
    def __init__(self, store, provider, pages: int = PAGES):
        self.store, self.provider, self.pages = store, provider, pages
        self.notes: list[str] = []
        self._inferred: dict[str, Label | None] = {}

    def lookup_many(self, pairs):
        return self.store.lookup_many(pairs)

    # -------------------------------------------------------------- the cluster step
    def infer(self, address: str, chain: str) -> Label | None:
        if chain != "bitcoin":
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
        who = fmt.short(address)
        owners = sorted({lab.entity for lab in found.values()})
        if len(owners) > 1:
            self._note(f"{who} was spent together with addresses labelled "
                       f"{' and '.join(owners)}: two owners in one cluster, so no label was "
                       "derived from it.")
            return None
        with_it = [lab for lab in found.values() if lab.address in cluster.direct]
        if not with_it:
            self._note(f"{who} is in one wallet cluster with addresses labelled {owners[0]}, "
                       "but only through other addresses: it was never spent in one "
                       "transaction with any of them, so no label was derived from it.")
            return None
        best = max(with_it, key=lambda lab: (_weight(lab), lab.address))
        if best.category not in VASP_CATEGORIES or best.entity == NO_OWNER:
            what = "an exchange tag that names no owner" if best.entity == NO_OWNER \
                else f"{best.entity} ({best.category})"
            self._note(f"{who} was spent together with {best.address}, which is labelled "
                       f"{what}. A cluster label is only derived for a named exchange, so "
                       "none was; look at that address.")
            return None
        return self._label(address, chain, cluster, len(found), with_it, best, len(txs), whole)

    def _label(self, address: str, chain: str, cluster: Cluster, labelled: int,
               with_it: list[Label], best: Label, n_txs: int, whole: bool) -> Label:
        n, confidence = len(cluster.members), round(_weight(best) * CO_SPEND, 4)
        said = f" (\"{best.label}\")" if best.label else ""
        read = (f"all {_plural(n_txs, 'transaction')} of the address" if whole else
                f"the {_plural(n_txs, 'most recent transaction')} of the address; older ones, "
                "if it has any, were not read")
        evidence = (
            f"Wallet cluster: cluster of {n} addresses, {labelled} labelled {best.entity}. "
            f"{fmt.short(address)} was itself spent together with "
            f"{_plural(len(cluster.direct), 'other address', 'other addresses')} in "
            f"{_plural(len(cluster.links), 'transaction')} (the inputs of one transaction are "
            "signed by one owner; transactions with the shape of a CoinJoin or another joint "
            f"payment are left out). Labelled address spent with it: {best.address}{said}, "
            f"{fmt.tier_words(best.tier)}, source {best.source}. Transaction with both among "
            f"its inputs: {cluster.direct[best.address][0]}. Rule confidence {confidence:.3f} "
            f"= {_weight(best):.2f} (that label) x {CO_SPEND:.2f} (spent together), hand-set, "
            f"not calibrated. Read from {read}.")
        many = _plural(len(with_it), f"labelled {best.entity} address",
                       f"labelled {best.entity} addresses")
        return Label(address=address, chain=chain, entity=best.entity, category=best.category,
                     kind="unknown", tier="derived", source=CLUSTER_SOURCE, source_url=None,
                     label=f"{best.entity} wallet ({CLUSTER_MARK} {many})",
                     confidence=confidence, evidence=evidence)


def cluster_labels(chain: str, labels, provider):
    """`labels` as a Bitcoin trace needs them; unchanged for every other chain."""
    return ClusterLabels(labels, provider) if chain == "bitcoin" else labels
