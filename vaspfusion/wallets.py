"""What the stored cases say about one address: the transfers they read of it, and what
is on record against it.

This is not the wallet's history. A case reads the transfers of the wallets its trace
went through, so the figures here cover exactly those, and the page says so. The risk
block is risk.py's indicator score: every reason is a sentence about a stored fact.
"""
from __future__ import annotations

from .risk import wallet_risk

TOP = 5


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

    mine = [c for c in cases if c.get("chain") == chain]
    return {"risk": wallet_risk(address, label, mine),
            "inbound": _flow(inbound, "source"), "outbound": _flow(outbound, "target"),
            "flows_from_cases": used}
