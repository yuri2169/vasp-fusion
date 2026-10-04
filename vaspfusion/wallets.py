"""What the stored cases say about one address: the transfers they read of it, and what
is on record against it.

This is not the wallet's history. A case reads the transfers of the wallets its trace
went through, so the figures here cover exactly those, and the page says so. No risk
score is computed: `level` is a plain rule over labels and flags, and every reason is a
sentence about a stored fact.
"""
from __future__ import annotations

from .labels.threats import named as threat_words, tag_of

RISK_LABELS = {"sanctioned": "is on a sanctions list",
               "mixer": "is labelled as a mixer",
               "scam": "is labelled as a scam address"}
TOP = 5


def _ref(case: dict) -> str:
    return case.get("case_ref") or case["id"]


def _flow(edges: list[dict], other: str) -> dict | None:
    if not edges:
        return None
    assets = {e["asset"] for e in edges}
    usd = [e["amount_usd"] for e in edges if e.get("amount_usd") is not None]
    times = sorted(e["block_time"] for e in edges if e.get("block_time"))
    by_party: dict[str, float] = {}
    for e in edges:
        by_party[e[other]] = by_party.get(e[other], 0.0) + (e.get("amount") or 0.0)
    ranked = sorted(by_party, key=lambda a: (-by_party[a], a))
    one = len(assets) == 1
    return {"tx_count": len(edges),
            "total_usd": round(sum(usd), 2) if usd else None,
            "total": round(sum(e.get("amount") or 0.0 for e in edges), 8) if one else None,
            "asset": next(iter(assets)) if one else None,
            "first_seen": times[0] if times else None,
            "last_seen": times[-1] if times else None,
            "counterparties": len(by_party),
            "top_counterparties": ranked[:TOP]}


def wallet_view(address: str, chain: str, cases: list[dict], label: dict | None) -> dict:
    """`risk`, `inbound`, `outbound` and `flows_from_cases` of `WalletDetail`. `cases` are
    the finished case details this address appears in."""
    seen: set[tuple] = set()
    inbound, outbound = [], []
    used = 0
    for case in cases:
        if case.get("chain") != chain:
            continue
        hit = False
        for e in case.get("graph", {}).get("edges", []):
            if address not in (e["source"], e["target"]):
                continue
            key = (e.get("tx_hash"), e["source"], e["target"], e["asset"], e["amount"])
            hit = True
            if key in seen:           # the same transfer read by two cases counts once
                continue
            seen.add(key)
            (outbound if e["source"] == address else inbound).append(e)
        used += hit

    level, reasons = None, []
    if label or cases:
        level = "none"
    tag = tag_of(label)
    if tag is not None:
        level = "high"
        reasons.append(f"This address is tagged {threat_words(tag)}."
                       + (f" {tag['evidence']}" if tag.get("evidence") else ""))
    if label and label.get("category") in RISK_LABELS:
        level = "high"
        named = label.get("label") or label.get("entity")
        reasons.append(f"This address {RISK_LABELS[label['category']]}: {named} "
                       f"(source: {label['source']}).")
    for case in cases:
        for f in case.get("typology_flags", []):
            if f["wallet"] != address or f["severity"] not in ("high", "warn"):
                continue
            if f["severity"] == "high":
                level = "high"
            elif level != "high":
                level = "elevated"
            reasons.append(f"Case {_ref(case)}: {f['text']}")
        if (case.get("address") == address and level != "high"
                and case.get("outcome") == "SANCTIONED_OR_MIXER_REACHED"):
            level = "elevated"
            reasons.append(f"Case {_ref(case)}: funds this wallet sent reached a sanctioned "
                           "or mixer address.")
    return {"risk": {"score": None, "level": level, "reasons": reasons},
            "inbound": _flow(inbound, "source"), "outbound": _flow(outbound, "target"),
            "flows_from_cases": used}
