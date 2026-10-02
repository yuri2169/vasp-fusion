"""From finished cases to the desk: the unit of work is an exchange, not a complaint.

`routed_wallets` reads one stored case (the CaseDetail JSON, never the chain) and
returns the wallets a request can be made about: one per exchange the case names at
or above the bar. `build_desk` groups them across cases, one row per exchange, and
sets each row beside the requests already made. Nothing here guesses: a candidate
under the bar, an inbound one, or an exchange tag with no owner is never routed.
"""
from __future__ import annotations

from datetime import date, datetime

from ..attribute.rules import UNROUTABLE, RuleConfig

BAR = RuleConfig().attribute_min
USD_ASSETS = ("USDT", "USDC")          # amount_usd is the amount itself; no price feed
AWAITING = ("sent", "acknowledged")    # a reply is still owed

NEXT_ACTION = {
    "drafted": "Review and approve the draft",
    "approved": "Send through SAHYOG",
    "sent": "Await acknowledgement",
    "acknowledged": "Await the reply",
    "answered": "Review the reply",
    "freeze_confirmed": "Freeze confirmed: record it in the case file",
    "refused": "Refused: read the reason given and escalate",
}


def day(d: date | str) -> str:
    """9 Oct 2026"""
    d = date.fromisoformat(str(d)[:10]) if not isinstance(d, date) else d
    return f"{d.day} {d.strftime('%b %Y')}"


def _usd(amount: float | None, asset: str | None) -> float | None:
    return amount if amount is not None and asset in USD_ASSETS else None


def _path_hashes(candidate: dict) -> list[str]:
    """The transactions of the route, then any by which the account passed it all on."""
    seen: list[str] = []
    for item in candidate.get("evidence", []):
        if item["kind"] == "path":
            seen += [h for h in item.get("tx_hashes", []) if h not in seen]
    return seen


def _amount(case: dict, candidate: dict) -> float | None:
    if candidate.get("amount") is not None:
        return candidate["amount"]
    # a case stored before B8: the exact sum is in where_funds_went, the share is rounded
    for part in case.get("where_funds_went", []):
        if part["kind"] == "vasp" and part["name"] == candidate["vasp"]:
            return part["amount"]
    return None


def candidate_wallet(case: dict, c: dict) -> dict:
    """One candidate of a case as a wallet row (routable or not)."""
    amount = _amount(case, c)
    return {
        "vasp": c["vasp"], "category": c["category"], "direction": c["direction"],
        "case_id": case["id"], "case_ref": case.get("case_ref"),
        "complaint_no": case.get("complaint_no"), "chain": case["chain"],
        "suspect": case["address"],
        "address": c.get("account_address") or c["deposit_address"],
        "entry_address": c["deposit_address"], "entry_label": c.get("entry_label"),
        "entry_kind": c.get("entry_kind"),
        "entry_addresses": c.get("entry_addresses") or [c["deposit_address"]],
        "tier": c["label_tier"], "confidence": c["confidence"],
        "confidence_interval": c.get("confidence_interval"),
        "counterfactual_holds": c.get("counterfactual_holds"),
        "hops": c["hops"], "share": c["share_of_funds"], "asset": case.get("asset"),
        "amount": amount, "amount_usd": _usd(amount, case.get("asset")),
        "reached_at": c.get("reached_at"), "tx_hashes": _path_hashes(c),
    }


def routable(c: dict, bar: float = BAR) -> bool:
    return (c["direction"] == "outbound" and c["confidence"] >= bar
            and c["vasp"] != UNROUTABLE)


def routed_wallets(case: dict, bar: float = BAR) -> list[dict]:
    """The wallets of a finished case a request can be made about, nearest first."""
    if case.get("status") != "done":
        return []
    return [candidate_wallet(case, c) for c in case.get("candidates", []) if routable(c, bar)]


def _covered(requests: list[dict]) -> set[tuple[str, str]]:
    """(case, wallet) pairs some request already asks about."""
    return {(w.get("case_id"), w["address"]) for r in requests for w in r["letter"]["wallets"]}


def _newest_first(requests: list[dict]) -> list[dict]:
    return sorted(requests, key=lambda r: (str(r["created_at"]), r["id"]), reverse=True)


def _overdue(request: dict, today: date) -> bool:
    return (request["status"] in AWAITING and request.get("due") is not None
            and date.fromisoformat(str(request["due"])[:10]) < today)


def build_desk(cases: list[dict], requests: list[dict], today: date,
               bar: float = BAR) -> dict:
    """`Desk`: one row per exchange (largest sum first), and the follow-ups due."""
    wallets: dict[str, list[dict]] = {}
    for case in cases:
        for w in routed_wallets(case, bar):
            wallets.setdefault(w["vasp"], []).append(w)
    by_vasp: dict[str, list[dict]] = {}
    for r in requests:
        by_vasp.setdefault(r["vasp"], []).append(r)

    rows = []
    for vasp in sorted(set(wallets) | set(by_vasp)):
        ws, rs = wallets.get(vasp, []), _newest_first(by_vasp.get(vasp, []))
        covered = _covered(rs)
        open_ws = [w for w in ws if (w["case_id"], w["address"]) not in covered]
        latest = rs[0] if rs else None
        if not ws:        # only the requests remain (their cases were removed or re-traced)
            wallet_count = len({w["address"] for r in rs for w in r["letter"]["wallets"]})
            total = sum(w.get("amount_usd") or 0.0 for w in latest["letter"]["wallets"])
            case_ids = sorted({c for r in rs for c in r["case_ids"]})
            category = "exchange"
        else:
            wallet_count = len({(w["chain"], w["address"]) for w in ws})
            total = sum(w["amount_usd"] or 0.0 for w in ws)
            case_ids = sorted({w["case_id"] for w in ws})
            category = ws[0]["category"]
        if latest is None:
            action = "Draft request"
        elif open_ws:
            n = len(open_ws)
            action = f"Draft a request for {n} wallet{'s' if n != 1 else ''} not yet requested"
        elif _overdue(latest, today):
            action = f"Follow up: the reply was due {day(latest['due'])}"
        else:
            action = NEXT_ACTION[latest["status"]]
            if latest["status"] in AWAITING and latest.get("due"):
                action += f" (reply due {day(latest['due'])})"
        rows.append({"vasp": vasp, "category": category, "wallet_count": wallet_count,
                     "total_usd": round(total, 2), "case_ids": case_ids,
                     "status": latest["status"] if latest else "not_requested",
                     "next_action": action,
                     "last_request_id": latest["id"] if latest else None,
                     "unrequested_wallets": len(open_ws)})
    rows.sort(key=lambda r: (-r["total_usd"], r["vasp"]))

    follow_ups = [{"kind": "reply_overdue", "vasp": r["vasp"], "request_id": r["id"],
                   "due": str(r["due"])[:10],
                   "text": f"{r['vasp']} has not replied; the reply was due {day(r['due'])}"}
                  for r in sorted(requests, key=lambda r: (str(r.get("due")), r["id"]))
                  if _overdue(r, today)]
    return {"follow_ups": follow_ups, "rows": rows}


SUMMARY_KEYS = ("id", "reference", "vasp", "status", "case_ids", "created_at", "due")


def vasp_detail(name: str, directory, label_counts: dict[str, int], cases: list[dict],
                requests: list[dict]) -> dict:
    """`VaspDetail`: the directory entry, how many labels we hold, every case wallet that
    touches this exchange (routed or not, either direction), and the requests made."""
    entry = directory.get(name)
    vasp = entry["name"]
    wallets = []
    for case in cases:
        if case.get("status") != "done":
            continue
        for c in case.get("candidates", []):
            if c["vasp"] != vasp:
                continue
            w = candidate_wallet(case, c)
            wallets.append({"address": w["address"], "chain": w["chain"],
                            "case_id": w["case_id"], "direction": w["direction"],
                            "amount_usd": w["amount_usd"], "tier": w["tier"],
                            "confidence": w["confidence"],
                            "routable": routable(c)})
    wallets.sort(key=lambda w: (not w["routable"], -(w["amount_usd"] or 0.0), w["case_id"]))
    mine = _newest_first([r for r in requests if r["vasp"] == vasp])
    return {"directory": entry, "label_counts": label_counts, "wallets": wallets,
            "requests": [{k: r.get(k) for k in SUMMARY_KEYS} for r in mine]}


def parse_time(value) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00"))
