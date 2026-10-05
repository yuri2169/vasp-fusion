"""Leads: unlabelled wallets on the trail that behave like an exchange deposit address.

The label store cannot name every exchange. When the wallet's money reached an
unlabelled wallet that the deposit-address model (B6) scores high, the case says so:
"this looks like a deposit address of an exchange we cannot name", and names the
wallet it sweeps into, because a label for that one wallet would settle it.

A lead never changes the outcome or any confidence. No VASP is named without a label.
The model was measured on exchange customers and deposit addresses only, so a wallet
that never dealt with an exchange is outside what was measured: every lead is worded
as something to check.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..chains.base import ProviderError
from ..explain import fmt
from ..labels.normalize import VASP_CATEGORIES
from ..trace import TraceNode, TraceResult
from .rules import UNROUTABLE, Attribution

CODE = "deposit_like"


@dataclass(frozen=True)
class LeadConfig:
    min_share: float = 0.05      # of the funds, to be worth a look
    max_wallets: int = 5         # scored per case (three listings each)
    min_p: float = 0.90          # the model's probability that makes a lead


def wallets_to_score(tr: TraceResult, cfg: LeadConfig = LeadConfig()) -> list[TraceNode]:
    """Unlabelled wallets the money reached that are not hubs, largest first. A hub pays
    out to many wallets, which a deposit address never does."""
    if not tr.total_out:
        return []
    # a wallet the money reached over a bridge is on another chain, which the model (and
    # the scorer's adapter) does not read
    nodes = [n for (side, _), n in tr.nodes.items()
             if side == "outbound" and n.label is None and n.state != "hub"
             and n.chain in (None, tr.chain)
             and float(n.received / tr.total_out) >= cfg.min_share]
    nodes.sort(key=lambda n: (-n.received, n.address))
    return nodes[:cfg.max_wallets]


def _reasons(score) -> str:
    said = [r["text"] for r in score.reasons if r["weight"] > 0]
    return f" What speaks for it: {'; '.join(said)}." if said else ""


def add_leads(tr: TraceResult, att: Attribution, scorer, labels,
              cfg: LeadConfig = LeadConfig()) -> list[str]:
    """Score the unlabelled wallets and write what was found into `att` (a flag, what
    would change an abstain, a next step). Returns notes for the case's provenance."""
    nodes = wallets_to_score(tr, cfg)
    if not nodes:
        return []
    if scorer is None:
        from ..classify.runtime import SCORED_CHAINS
        why = ("the model was not loaded for this run (`make model` writes its files)"
               if tr.chain in SCORED_CHAINS else
               "it is only used on Tron, where it recognised the deposit addresses of an "
               "exchange it had never seen")
        return [f"{len(nodes)} unlabelled wallet{'s' if len(nodes) != 1 else ''} on the trail "
                f"not scored by the deposit-address model: {why}."]
    notes, flags, change, steps = [], [], [], []
    scored = 0
    for node in nodes:
        into = tr.edges_into("outbound", node.address)
        try:
            score = scorer.score(node.address, min(e.transfer.block_time for e in into))
        except ProviderError as e:
            notes.append(f"{fmt.short(node.address)} could not be scored by the "
                         f"deposit-address model ({e}).")
            continue
        if score is None:                    # no usable transfer in the window: nothing to score
            continue
        scored += 1
        collector = score.collector
        if score.p < cfg.min_p or collector is None or collector == tr.address:
            continue
        who, share = fmt.short(node.address), node.received / tr.total_out
        lab = labels.lookup_many([(collector, tr.chain)]).get((collector, tr.chain))
        if lab is not None and lab.category not in VASP_CATEGORIES:
            continue        # it pays a bridge, a mixer, a named non-exchange: not a deposit address
        named = lab is not None and lab.entity != UNROUTABLE
        said = (f"{who} behaves like an exchange deposit address: {fmt.pct(share)} of the funds "
                f"({fmt.amount(node.received, tr.asset)}) reached it, and the deposit-address "
                f"model gives {fmt.prob(score.p)} ({fmt.prob_range(score.low, score.high)})."
                + _reasons(score))
        if named:
            said += (f" The wallet it pays most, {fmt.short(collector)}, is labelled "
                     f"{lab.entity} ({fmt.tier_words(lab.tier)}), so it may be a deposit address of {lab.entity} "
                     "that the discovery rules have not derived.")
            steps.append(f"Ask {lab.entity} whether {who} is one of its deposit addresses: it "
                         f"behaves like one and pays into {fmt.short(collector)} "
                         f"({fmt.pct(share)} of the funds reached it)")
        elif lab is not None:
            said += (f" The wallet it pays most, {fmt.short(collector)}, is tagged as an "
                     "exchange but the source names no owner, so the exchange cannot be named.")
            steps.append(f"Identify the exchange behind {fmt.short(collector)}: {who}, which "
                         f"received {fmt.pct(share)} of the funds, behaves like a deposit "
                         "address and pays into it")
        else:
            said += (f" Neither it nor {fmt.short(collector)}, the wallet it sweeps into, is "
                     "labelled, so the exchange cannot be named.")
            change.append(f"A label for {fmt.short(collector)}, the wallet {who} sweeps into: if "
                          f"it is an exchange's wallet, {who} is that exchange's deposit address "
                          f"({fmt.pct(share)} of the funds)")
            steps.append(f"Identify {fmt.short(collector)}: {who}, which received "
                         f"{fmt.pct(share)} of the funds, behaves like a deposit address and "
                         "sweeps into it (check other label sources and block explorers)")
        said += (" A lead to check, not a finding: the model was measured on exchange customers "
                 "and deposit addresses only.")
        flags.append({"code": CODE, "severity": "info", "wallet": node.address, "text": said,
                      "figures": {"p": score.p, "low": score.low, "high": score.high,
                                  "transfers_read": float(score.n_rows),
                                  "share": round(float(share), 4),
                                  "amount": float(node.received)},
                      "tx_hashes": sorted({e.transfer.tx_hash for e in into})})
    att.flags = att.flags + flags
    if att.outcome == "INSUFFICIENT_EVIDENCE":
        att.what_would_change = list(dict.fromkeys(change + att.what_would_change))
    # with no exchange named a lead is the first thing to do; otherwise it follows the request
    first = att.outcome == "INSUFFICIENT_EVIDENCE"
    att.next_steps = list(dict.fromkeys(steps + att.next_steps if first
                                        else att.next_steps + steps))
    notes.append(f"Deposit-address model: {scored} unlabelled wallet"
                 f"{'s' if scored != 1 else ''} on the trail scored, {len(flags)} "
                 f"behave{'s' if len(flags) == 1 else ''} like a deposit address.")
    return notes
