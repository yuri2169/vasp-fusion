"""Who to write to first, when a case reaches more than one exchange.

The order uses only what the tool holds: the share of the wallet's funds that reached
each exchange, when the funds last arrived there, whether the cited directory says the
exchange is registered with FIU-IND, and whether a channel for requests is on record.
Each exchange carries its reasons as sentences.

The order is a stated rule, not a prediction. No response time is given anywhere: the
tool holds no cited figure for how fast any exchange answers, and the only replies an
installation records are typed in by hand or played by the simulator.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..explain import fmt
from .routing import OPEN, day, routable

RULE = ("Exchanges registered with FIU-IND (as cited) come first: a notice under Indian "
        "law can be served on them. Then exchanges with a published law-enforcement "
        "channel, then the rest. Within each group: the larger share of the funds first, "
        "then the more recent arrival.")
NOTE = ("The order is this tool's rule, for the officer to weigh. No response time is "
        "stated: no cited figure is held for how fast any exchange answers.")

# the route a request to the exchange takes, from the directory's cited facts
DOMESTIC, DIRECT, OFFSHORE = "domestic_notice", "direct_channel", "letter_of_request"


def route_of(entry: dict) -> str:
    if entry.get("fiu_ind_registered") is True:
        return DOMESTIC
    return DIRECT if entry.get("le_request_channel") else OFFSHORE


def offers_letter_of_request(entry: dict) -> bool:
    """A letter-of-request draft is offered unless a source says the exchange is
    registered with FIU-IND (then the domestic notice applies)."""
    return entry.get("fiu_ind_registered") is not True


def _when(t: datetime) -> str:
    return f"{day(t.date())}, {t:%H:%M} UTC"


def _time(value) -> datetime:
    t = value if isinstance(value, datetime) else \
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def registration_reason(entry: dict) -> str:
    reg = entry.get("fiu_ind_registered")
    if reg is None:
        return ("No source was found for its FIU-IND registration: not on record, which "
                "is not a \"no\".")
    as_of = day(entry["fiu_ind_as_of"])
    if reg is False:
        return f"FIU-IND named it as operating without registration (as of {as_of})."
    kinds = {s.get("kind") for s in entry.get("sources", [])
             if s["field"] == "fiu_ind_registered"}
    if kinds == {"official"}:
        return f"Registered with FIU-IND as of {as_of} (an official list)."
    return f"Registered with FIU-IND as of {as_of}, on the exchange's own statement."


def write_order(case: dict, directory, requests: list[dict] = ()) -> dict | None:
    """`WriteOrder` for one finished case: every exchange a request can be drafted on,
    in the order to write to them, each with its reasons. None when there is none."""
    if case.get("status") != "done":
        return None
    found: dict[str, dict] = {}
    for c in case.get("candidates", []):
        if not routable(c):
            continue
        vasp = directory.canonical(c["vasp"])
        x = found.setdefault(vasp, {"share": 0.0, "amount": 0.0, "arrivals": []})
        x["share"] += c["share_of_funds"]
        x["amount"] += sum(w["amount"] for w in c["request_wallets"])
        x["arrivals"] += [_time(w["reached_at"]) for w in c["request_wallets"]]
    if not found:
        return None
    asset = case.get("asset")
    newest = max(max(x["arrivals"]) for x in found.values())
    by_vasp = {}
    for r in sorted(requests, key=lambda r: (str(r["created_at"]), r["id"])):
        if case["id"] in r["case_ids"] and r["status"] in OPEN:
            by_vasp[r["vasp"]] = r
    rows = []
    for vasp, x in found.items():
        entry = directory.get(vasp)
        route, last = route_of(entry), max(x["arrivals"])
        share = min(round(x["share"], 4), 1.0)
        reasons = [("Under 1%" if share < 0.01 else f"{share:.0%}") + " of the wallet's "
                   f"funds reached it ({fmt.amount(str(round(x['amount'], 6)), asset)})."]
        arrived = f"The funds last arrived there on {_when(last)}"
        if len(found) > 1 and last == newest:
            arrived += ", the most recent arrival among these exchanges"
        reasons.append(arrived + ".")
        reasons.append(registration_reason(entry))
        reasons.append(f"A law-enforcement channel is on record: {entry['le_request_channel']}."
                       if entry.get("le_request_channel")
                       else "No law-enforcement channel is on record for it.")
        req = by_vasp.get(vasp)
        rows.append({
            "vasp": vasp, "share_of_funds": share, "amount": round(x["amount"], 6),
            "asset": asset, "last_arrival": last.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fiu_ind_registered": entry.get("fiu_ind_registered"),
            "fiu_ind_as_of": entry.get("fiu_ind_as_of"),
            "channel_on_record": bool(entry.get("le_request_channel")),
            "route": route, "letter_of_request": offers_letter_of_request(entry),
            "reasons": reasons, "request_id": req["id"] if req else None,
            "request_status": req["status"] if req else None})
    tier = {DOMESTIC: 0, DIRECT: 1, OFFSHORE: 2}
    rows.sort(key=lambda r: (tier[r["route"]], -r["share_of_funds"],
                             -_time(r["last_arrival"]).timestamp(), r["vasp"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return {"rule": RULE, "note": NOTE, "exchanges": rows}
