"""The paragraph at the top of a case file: what the wallet did, where its money
went, which exchange (if any) to write to, and how sure the rules are.

Written for the investigating officer, so it states amounts, shares, hops, times
and the kind of label behind each name, and lists the transaction hashes that
back the main path. Exchanges that received a share are listed with that share, but
only the one the rules named is presented as the answer ("Nearest exchange: ...").
"""
from __future__ import annotations

from ..attribute.rules import Attribution, Candidate, RuleConfig
from ..trace import TraceResult
from . import fmt

CHAIN_NAMES = {"tron": "Tron", "ethereum": "Ethereum", "bsc": "BNB Smart Chain",
               "polygon": "Polygon", "arbitrum": "Arbitrum", "base": "Base",
               "optimism": "Optimism", "avalanche": "Avalanche", "bitcoin": "Bitcoin",
               "solana": "Solana"}
MAX_CANDIDATES = 3


def _day(dt) -> str:
    return f"{dt.day} {dt:%b %Y}"


def _opening(tr: TraceResult) -> str:
    chain = CHAIN_NAMES.get(tr.chain, tr.chain.title())
    who = fmt.short(tr.address)
    if tr.asset is None:
        if tr.notes and "not traced" in tr.notes[0]:
            return tr.notes[0]
        return (f"Wallet {who} has not sent any funds that can be traced on {chain} (no "
                f"outgoing stablecoin or native-coin transfers above dust).")
    first = sorted((e.transfer for e in tr.edges if e.side == "outbound" and e.hop == 1),
                   key=lambda t: t.block_time)
    n = len(first)
    sent = f"Wallet {who} sent {fmt.amount(tr.total_out, tr.asset)} on {chain}"
    if not first:       # Bitcoin: every spend went into a transaction that is not followed
        return f"{sent}, and none of it could be followed past the wallet's own transactions."
    when = (f"on {_day(first[0].block_time)}" if _day(first[0].block_time) == _day(first[-1].block_time)
            else f"between {_day(first[0].block_time)} and {_day(first[-1].block_time)}")
    followed = sum((t.amount for t in first), tr.total_out * 0)
    if followed < tr.total_out:
        return (f"{sent}: {fmt.amount(followed, tr.asset)} in {n} transfer{'s' if n != 1 else ''} "
                f"{when}, and {fmt.amount(tr.total_out - followed, tr.asset)} in transactions "
                "that could not be followed.")
    return f"{sent} in {n} transfer{'s' if n != 1 else ''} {when}."


def _reached(tr: TraceResult, c: Candidate) -> str:
    text = (f"{fmt.amount(c.amount, tr.asset)} ({fmt.pct(c.share)}) reached {c.vasp} in "
            f"{fmt.hops(c.hops_min, c.hops_max)}")
    if len(c.path_edges) > 1 and c.hops_max == c.hops_min:
        text += f" within {fmt.duration(c.time_to_reach_s)}"
    text += f", at {fmt.short(c.deposit_address)}"
    name = f"\"{c.label.label}\", " if c.label.label else ""
    text += f" ({name}{fmt.tier_words(c.label.tier)})."
    if c.passed_all:
        text += (f" The wallet before it, {fmt.short(c.last_hop)}, passed on everything it "
                 f"received from this trail.")
    return text


def path_hashes(tr: TraceResult, att: Attribution) -> list[str]:
    """Hashes of the path the case leads with: the named candidate, else the alert,
    else the nearest candidate."""
    if att.top is not None:
        return [e.transfer.tx_hash for e in att.top.path_edges]
    alert = next((f for f in att.flags if f["severity"] == "high"
                  and ("outbound", f["wallet"]) in tr.nodes), None)
    if att.outcome == "SANCTIONED_OR_MIXER_REACHED" and alert is not None:
        return [e.transfer.tx_hash for e in tr.path_to("outbound", alert["wallet"])]
    out = [c for c in att.candidates if c.direction == "outbound"]
    return [e.transfer.tx_hash for e in out[0].path_edges] if out else []


def narrative(tr: TraceResult, att: Attribution, rules: RuleConfig = RuleConfig()) -> str:
    parts = [_opening(tr)]
    untraced_service = tr.asset is None and bool(tr.notes) and "not traced" in tr.notes[0]
    alerts = [f["text"] + "." for f in att.flags if f["severity"] == "high"
              and not (untraced_service and f["wallet"] == tr.address)]   # the opening said it
    out = [c for c in att.candidates if c.direction == "outbound" and c.hops > 0]
    reached = [_reached(tr, c) for c in out[:MAX_CANDIDATES]]
    if len(out) > MAX_CANDIDATES:
        reached.append(f"{len(out) - MAX_CANDIDATES} more exchanges received smaller shares.")
    parts += alerts + reached if att.outcome == "SANCTIONED_OR_MIXER_REACHED" else reached + alerts

    if att.top is not None and att.top.confidence_interval is not None:
        low, high = att.top.confidence_interval
        parts.append(f"Nearest exchange: {att.top.vasp}, confidence {att.top.confidence:.2f} "
                     f"({fmt.prob_range(low, high)}). The range comes from the deposit-address "
                     "model, which is calibrated against the addresses the discovery rules "
                     "derived; the weight of the exchange wallet's label and the hop decay are "
                     "rule-set.")
    elif att.top is not None:
        parts.append(f"Nearest exchange: {att.top.vasp}, rule confidence "
                     f"{att.top.confidence:.2f} (rule-based, not calibrated).")
    elif att.outcome == "INSUFFICIENT_EVIDENCE":
        parts.append("No exchange is named. " + (att.abstain_reason or ""))
    elif out:
        parts.append(f"No exchange clears the {rules.attribute_min:.2f} rule confidence needed "
                     "to name one.")
    else:
        parts.append("No labelled exchange was reached.")

    if att.top is not None and att.top.counterfactual:
        parts.append("Checked without its strongest evidence: " + att.top.counterfactual)
    leads = [f for f in att.flags if f["code"] == "deposit_like"]
    if leads:
        more = f", and {len(leads) - 1} more" if len(leads) > 1 else ""
        parts.append("Lead, not a finding: " + leads[0]["text"].split(". ", 1)[0]
                     + f"{more}; see the flags.")
    for c in [c for c in att.candidates if c.direction == "inbound"][:2]:
        parts.append(f"The wallet received {fmt.amount(tr.total_in, tr.in_asset)}; "
                     f"{fmt.pct(c.share)} came directly from {c.vasp} "
                     f"({fmt.short(c.deposit_address)})." if c.hops == 1 else
                     f"The wallet received {fmt.amount(tr.total_in, tr.in_asset)}; "
                     f"{fmt.pct(c.share)} traces back to {c.vasp} in {fmt.hops(c.hops)}.")
    if tr.untraced:
        items = [f"{fmt.amount(total, asset)} in {n} transfer{'s' if n != 1 else ''}"
                 for asset, (n, total) in tr.untraced.items()]
        parts.append("Not followed in this run: " + ", ".join(items) + ".")
    parts += [n for n in tr.notes if "not traced" not in n]
    hashes = path_hashes(tr, att)
    if hashes:
        parts.append("Transaction hashes: " + ", ".join(hashes) + ".")
    return " ".join(p.strip() for p in parts if p and p.strip())
