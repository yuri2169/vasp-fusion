"""The dashboard's figures, counted from the stored cases, the desk and the watchlist.

Nothing here reads a chain or estimates anything: each number is a count of stored
records, and each has a list behind it that the interface links to.
"""
from __future__ import annotations

from statistics import median

from .desk.routing import AWAITING

OUTCOMES = ("ATTRIBUTED", "INSUFFICIENT_EVIDENCE", "SANCTIONED_OR_MIXER_REACHED")
REPLIED = ("answered", "freeze_confirmed", "refused")   # the exchange has had its say
TRACING = ("queued", "running")
MAX_ALERTS = 12


def _named(case: dict) -> dict | None:
    """The candidate a finished case names (`top_vasp`), if it names one."""
    if case.get("status") != "done" or not case.get("top_vasp"):
        return None
    for c in case.get("candidates", []):
        if c["vasp"] == case["top_vasp"] and c.get("direction", "outbound") == "outbound":
            return c
    return None


def case_alerts(case: dict) -> list[dict]:
    """One alert per high-severity flag of a finished case, in the flag's own words."""
    if case.get("status") != "done":
        return []
    ref = case.get("case_ref") or case["id"]
    return [{"wallet": f["wallet"], "chain": case["chain"], "severity": "high",
             "at": case["created_at"], "case_id": case["id"], "threat": f.get("threat"),
             "text": f"Case {ref}: {f['text']}"}
            for f in case.get("typology_flags", []) if f["severity"] == "high"]


def build_dashboard(cases: list[dict], desk: dict, requests: list[dict],
                    watch_alerts: list[dict] | None = None, watched: int = 0) -> dict:
    """`Dashboard` without `label_coverage`. `cases` are full case details, `desk` is
    `build_desk`'s answer for the same cases, `requests` every stored request."""
    done = [c for c in cases if c.get("status") == "done"]
    tracing = [c for c in cases if c.get("status") in TRACING]

    # A case is open while it is being traced, or while an exchange it routes a wallet
    # to has not replied (or has not been asked yet).
    open_ids = {c["id"] for c in tracing}
    awaiting_request = 0
    for row in desk.get("rows", []):
        if row["unrequested_wallets"] or row["status"] == "not_requested":
            awaiting_request += 1
        if row["unrequested_wallets"] or row["status"] not in REPLIED:
            open_ids.update(row["case_ids"])
    known = {c["id"] for c in cases}

    outcomes = {o: 0 for o in OUTCOMES}
    for c in done:
        if c.get("outcome") in outcomes:
            outcomes[c["outcome"]] += 1

    chains: dict[str, int] = {}
    for c in cases:
        chains[c["chain"]] = chains.get(c["chain"], 0) + 1

    times = [n["time_to_reach_s"] for n in map(_named, done)
             if n is not None and n.get("time_to_reach_s") is not None]

    alerts = [a for c in done for a in case_alerts(c)] + list(watch_alerts or [])
    alerts.sort(key=lambda a: (str(a["at"]), a["wallet"], a["text"]), reverse=True)

    return {
        "counts": {
            "cases_total": len(cases),
            "open_cases": len(open_ids & known),
            "wallets_attributed": outcomes["ATTRIBUTED"],
            "requests_awaiting_reply": sum(1 for r in requests if r["status"] in AWAITING),
            "tracing": len(tracing),
            "failed": sum(1 for c in cases if c.get("status") == "failed"),
            "awaiting_request": awaiting_request,
            "watched": watched,
        },
        "outcomes": outcomes,
        "top_vasps": [{"vasp": r["vasp"], "cases": len(r["case_ids"]),
                       "total_usd": r["total_usd"]}
                      for r in desk.get("rows", []) if r["case_ids"]][:10],
        "chain_mix": [{"chain": k, "cases": v}
                      for k, v in sorted(chains.items(), key=lambda kv: (-kv[1], kv[0]))],
        "median_time_to_attribution_s": float(median(times)) if times else None,
        "attribution_times_n": len(times),
        "recent_alerts": alerts[:MAX_ALERTS],
    }
