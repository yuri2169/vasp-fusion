"""From finished cases to the desk: the unit of work is an exchange, not a complaint.

`routed_wallets` reads one stored case (the CaseDetail JSON, never the chain) and
returns the wallets a request can be made about: one per exchange the case names at
or above the bar. `build_desk` groups them across cases, one row per exchange, and
sets each row beside the requests already made. Nothing here guesses: a candidate
under the bar, an inbound one, or an exchange tag with no owner is never routed.
"""
from __future__ import annotations

from datetime import date

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
OPEN = ("drafted", "approved", "sent", "acknowledged", "answered", "freeze_confirmed",
        "refused")                      # every status but withdrawn: the wallets were asked about


def day(d: date | str) -> str:
    """9 Oct 2026"""
    d = date.fromisoformat(str(d)[:10]) if not isinstance(d, date) else d
    return f"{d.day} {d.strftime('%b %Y')}"


def _usd(amount: float | None, asset: str | None) -> float | None:
    return amount if amount is not None and asset in USD_ASSETS else None


def _same(name: str) -> str:
    return name


def routable(c: dict, bar: float = BAR) -> bool:
    """Can a request be drafted on this candidate? Only if the wallet's own money went
    there (outbound, at least one hop: the VASP's own wallet is asked about directly,
    not by letter), the confidence clears the bar, the source names an owner, and the
    case says which wallets to ask about (cases stored before B8 do not)."""
    return (c["direction"] == "outbound" and c["hops"] >= 1 and c["confidence"] >= bar
            and c["vasp"] != UNROUTABLE and bool(c.get("request_wallets")))


def routed_wallets(case: dict, bar: float = BAR, canonical=_same) -> list[dict]:
    """The wallets of a finished case a request can be made about: for each exchange the
    case names (nearest first), every wallet the money went through, largest first, each
    with its own amount. `canonical` maps a label's spelling of an exchange to the
    directory's ("Coinswitch" and "CoinSwitch" are one exchange)."""
    if case.get("status") != "done":
        return []
    out = []
    for c in case.get("candidates", []):
        if not routable(c, bar):
            continue
        for w in c["request_wallets"]:
            out.append({
                "vasp": canonical(c["vasp"]), "category": c["category"],
                "case_id": case["id"], "case_ref": case.get("case_ref"),
                "complaint_no": case.get("complaint_no"), "chain": case["chain"],
                "suspect": case["address"], "address": w["address"],
                "paid_into": w.get("paid_into"), "label": w.get("label"),
                "kind": w.get("kind"), "tier": w["tier"], "confidence": c["confidence"],
                "confidence_interval": c.get("confidence_interval"),
                "counterfactual_holds": c.get("counterfactual_holds"), "hops": c["hops"],
                "asset": case.get("asset"), "amount": w["amount"],
                "amount_usd": _usd(w["amount"], case.get("asset")),
                "reached_at": w["reached_at"], "tx_hashes": w["tx_hashes"]})
    return out


def _covered(requests: list[dict]) -> set[tuple[str, str]]:
    """(case, wallet) pairs some request already asks about."""
    return {(w.get("case_id"), w["address"]) for r in requests for w in r["letter"]["wallets"]}


def _newest_first(requests: list[dict]) -> list[dict]:
    return sorted(requests, key=lambda r: (str(r["created_at"]), r["id"]), reverse=True)


def _overdue(request: dict, today: date) -> bool:
    return (request["status"] in AWAITING and request.get("due") is not None
            and date.fromisoformat(str(request["due"])[:10]) < today)


def build_desk(cases: list[dict], requests: list[dict], today: date,
               bar: float = BAR, canonical=_same) -> dict:
    """`Desk`: one row per exchange (largest sum first), and the follow-ups due.
    A withdrawn request counts for nothing here: its wallets are open again."""
    wallets: dict[str, list[dict]] = {}
    for case in cases:
        for w in routed_wallets(case, bar, canonical):
            wallets.setdefault(w["vasp"], []).append(w)
    by_vasp: dict[str, list[dict]] = {}
    for r in requests:
        if r["status"] != "withdrawn":
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
    touches this exchange, and the requests made. Wallets a request can be drafted on
    come first; the rest (under the bar, the exchange's own wallet, or the exchange
    funded the wallet) are context, marked `routable: false`."""
    entry = directory.get(name)
    vasp = entry["name"]
    wallets = []
    for case in cases:
        if case.get("status") != "done":
            continue
        for w in routed_wallets(case, canonical=directory.canonical):
            if w["vasp"] == vasp:
                wallets.append({"address": w["address"], "chain": w["chain"],
                                "case_id": w["case_id"], "direction": "outbound",
                                "amount_usd": w["amount_usd"], "tier": w["tier"],
                                "confidence": w["confidence"], "routable": True})
        for c in case.get("candidates", []):
            if directory.canonical(c["vasp"]) != vasp or routable(c):
                continue
            outbound = c["direction"] == "outbound"
            wallets.append({"address": c["deposit_address"], "chain": case["chain"],
                            "case_id": case["id"], "direction": c["direction"],
                            # what an exchange sent the wallet is in the inbound asset,
                            # which a case does not record: no dollar figure for it
                            "amount_usd": _usd(c.get("amount"), case.get("asset"))
                            if outbound else None,
                            "tier": c["label_tier"], "confidence": c["confidence"],
                            "routable": False})
    wallets.sort(key=lambda w: (not w["routable"], -(w["amount_usd"] or 0.0), w["case_id"],
                                w["address"]))
    mine = _newest_first([r for r in requests if r["vasp"] == vasp])
    return {"directory": entry, "label_counts": label_counts, "wallets": wallets,
            "requests": [{k: r.get(k) for k in SUMMARY_KEYS} for r in mine]}
