"""The watchlist: has a watched wallet done anything since the officer last looked?

A watched wallet keeps a baseline: a snapshot of its case taken when it was added, or
when its changes were last marked as seen. "Check now" traces the wallet again; the list
then compares the case as it is now with the baseline and says what is new, in
sentences. Nothing runs in the background and nothing is estimated: a change is a
difference between two stored traces.
"""
from __future__ import annotations

from .desk.routing import day

HIGH = "high"


def _own(case: dict) -> list[dict]:
    a = case["address"]
    return [e for e in case.get("graph", {}).get("edges", []) if a in (e["source"], e["target"])]


def snapshot(case: dict) -> dict:
    """What is compared between two traces of one wallet."""
    own = _own(case)
    times = sorted(e["block_time"] for e in own if e.get("block_time"))
    return {
        "case_id": case["id"],
        "traced_at": (case.get("provenance") or {}).get("fetched_at") or case["created_at"],
        "transfers": sorted({e["tx_hash"] for e in own if e.get("tx_hash")}),
        "last_transfer_at": times[-1] if times else None,
        "exchanges": sorted({c["vasp"] for c in case.get("candidates", [])}),
        "alerts": sorted({f["code"] for f in case.get("typology_flags", [])
                          if f["severity"] == HIGH}),
        "threat_links": sorted({_link(f) for f in case.get("typology_flags", [])
                                if f.get("threat")}),
        "outcome": case.get("outcome"),
    }


def _link(flag: dict) -> str:
    """A link to a tagged address, as a snapshot remembers it."""
    return f"{flag['threat']['threat']}:{flag['wallet']}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def changes(baseline: dict | None, case: dict) -> list[dict]:
    """What the case shows now that the baseline did not, newest kind of news first."""
    if baseline is None:
        return []
    now = snapshot(case)
    at = now["traced_at"]
    out = []
    # a baseline taken before threat tags existed has no list of links: nothing is "new"
    known = baseline.get("threat_links")
    linked = set()
    for flag in case.get("typology_flags", []) if known is not None else []:
        if flag.get("threat") and _link(flag) not in known:
            linked.add(flag["code"])
            out.append({"kind": "new_threat_link", "severity": "high", "at": at,
                        "threat": flag["threat"],
                        "text": f"New link to a tagged address: {flag['text']}"})
    for code in now["alerts"]:
        if code not in baseline["alerts"] and code not in linked:
            flag = next(f for f in case["typology_flags"]
                        if f["code"] == code and f["severity"] == HIGH)
            out.append({"kind": "new_alert", "severity": "high", "at": at,
                        "text": f"New alert: {flag['text']}"})
    for vasp in now["exchanges"]:
        if vasp in baseline["exchanges"]:
            continue
        cand = next(c for c in case["candidates"] if c["vasp"] == vasp)
        how = ("funded this wallet" if cand.get("direction") == "inbound"
               else f"was reached, {_plural(cand['hops'], 'hop')} away")
        out.append({"kind": "new_exchange", "severity": "warn", "at": at,
                    "text": f"New exchange contact: {vasp} {how}"})
    seen = set(baseline["transfers"])
    fresh = [e for e in _own(case) if e.get("tx_hash") and e["tx_hash"] not in seen]
    hashes = {e["tx_hash"] for e in fresh}
    if hashes:
        latest = max(e["block_time"] for e in fresh)
        out.append({"kind": "new_activity", "severity": "info", "at": at,
                    "text": f"{_plural(len(hashes), 'new transfer')} of this wallet, "
                            f"the latest on {day(latest[:10])}"})
    return out


def state_of(case: dict | None, tracing: bool, found: list[dict]) -> str:
    if tracing or (case and case.get("status") in ("queued", "running")):
        return "checking"
    if case is None:
        return "not_traced"
    if case.get("status") == "failed" or case.get("error"):
        return "failed"
    return "changed" if found else "unchanged"


def watch_item(entry: dict, case: dict | None, tracing: bool = False,
               label: dict | None = None) -> dict:
    """`WatchItem`: a stored entry with what its wallet's case says now."""
    done = case is not None and case.get("status") == "done" and case.get("candidates") is not None
    found = changes(entry.get("baseline"), case) if done else []
    return {
        "id": entry["id"], "chain": entry["chain"], "address": entry["address"],
        "note": entry.get("note"), "added_at": entry["added_at"],
        "added_by": entry.get("added_by"),
        "case_id": case["id"] if case else None,
        "state": state_of(case, tracing, found),
        "last_checked_at": snapshot(case)["traced_at"] if done else None,
        "baseline_at": (entry.get("baseline") or {}).get("traced_at"),
        "changes": found,
        "error": case.get("error") if case else None,
        "label": label,
    }


def alerts_of(item: dict) -> list[dict]:
    """A watched wallet's changes as dashboard alerts."""
    return [{"wallet": item["address"], "chain": item["chain"], "severity": c["severity"],
             "at": c["at"], "case_id": item["case_id"], "threat": c.get("threat"),
             "text": f"Watched wallet: {c['text']}"} for c in item["changes"]]
