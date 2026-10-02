"""The flow diagram of a case, as plain data: numbered wallets in columns by hop, and
the arrows between them. `case_pdf.py` draws it; nothing here knows about PDF.

Every wallet of the case gets a number (W0 is the traced wallet). The diagram shows
the numbers; the wallet table beside it gives each number's full address, so the
picture stays readable and no address is shortened.
"""
from __future__ import annotations

ROLE_WORDS = {
    "suspect": "Traced wallet", "intermediary": "Unlabelled wallet",
    "exchange_hot": "Exchange hot wallet", "exchange_deposit": "Exchange deposit address",
    "exchange": "Exchange wallet", "custodial_wallet": "Custodial wallet",
    "swap_service": "Swap service", "bridge": "Bridge", "mixer": "Mixer",
    "sanctioned": "Sanctioned address", "hub": "High-activity wallet (not followed)",
    "unknown": "Unlabelled wallet (not followed)",
}
MAX_BOXES = 18
MAX_ROWS = 7


def wallet_index(case: dict) -> list[dict]:
    """Every wallet in the case's graph, numbered. Column 0 is the traced wallet,
    columns 1.. are hops away from it, column -1 holds the wallets that funded it.
    `amount` is the traced money that reached the wallet (for a funder: that it sent)."""
    g = case["graph"]
    origin = case["address"]
    into: dict[str, float] = {}
    sent_in: dict[str, float] = {}
    outbound: set[str] = set()
    for e in g["edges"]:
        traced = e.get("traced_amount") or 0.0
        if e.get("direction", "outbound") == "inbound":
            sent_in[e["source"]] = sent_in.get(e["source"], 0.0) + traced
        else:
            into[e["target"]] = into.get(e["target"], 0.0) + traced
            outbound.update((e["source"], e["target"]))
    rows = []
    for n in g["nodes"]:
        addr = n["id"]
        if addr == origin:
            col, amount = 0, case.get("total_sent") or 0.0
        elif addr in outbound or addr not in sent_in:
            col, amount = max(1, n["hop"]), into.get(addr, 0.0)
        else:
            col, amount = -1, sent_in[addr]
        label = n.get("label") or {}
        rows.append({"address": addr, "col": col, "role": n["role"], "amount": amount,
                     "entity": label.get("entity"), "tier": label.get("tier"),
                     "label": label.get("label"),
                     "title": label.get("entity") if label.get("entity")
                     and n["role"] not in ("intermediary", "unknown", "hub", "suspect")
                     else ROLE_WORDS[n["role"]].split(" (")[0]})
    rows.sort(key=lambda r: (r["col"] != 0, r["col"] < 0, abs(r["col"]), -r["amount"],
                             r["address"]))
    for i, r in enumerate(rows):
        r["n"] = i
    return rows


def _must_show(case: dict) -> set[str]:
    keep = {case["address"]}
    for c in case["candidates"]:
        keep.update(c["path"])
    for h in case["hop_rail"]:
        keep.update((h["from_address"], h["to_address"]))
    return keep


def layout(case: dict, index: list[dict] | None = None, max_boxes: int = MAX_BOXES,
           max_rows: int = MAX_ROWS) -> dict:
    """Boxes (wallet number, column, row) and arrows for the diagram. At most
    `max_boxes` wallets and `max_rows` per column are drawn: the wallets on a
    candidate's path first, then the largest. The rest are counted in `omitted`."""
    index = wallet_index(case) if index is None else index
    must = _must_show(case)
    ranked = sorted(index, key=lambda r: (r["address"] not in must, -r["amount"], r["n"]))
    per_col: dict[int, int] = {}
    kept = []
    for r in ranked:
        if len(kept) >= max_boxes or per_col.get(r["col"], 0) >= max_rows:
            continue
        per_col[r["col"]] = per_col.get(r["col"], 0) + 1
        kept.append(r)
    cols = sorted({r["col"] for r in kept})
    boxes = []
    for col in cols:
        column = sorted((r for r in kept if r["col"] == col), key=lambda r: r["n"])
        for row, r in enumerate(column):
            boxes.append({"n": r["n"], "address": r["address"], "col": cols.index(col),
                          "row": row, "role": r["role"], "title": r["title"],
                          "amount": r["amount"]})
    shown = {b["address"] for b in boxes}
    merged: dict[tuple[str, str, str], dict] = {}
    for e in case["graph"]["edges"]:
        if e["source"] not in shown or e["target"] not in shown:
            continue
        key = (e["source"], e["target"], e.get("direction", "outbound"))
        a = merged.setdefault(key, {"source": e["source"], "target": e["target"],
                                    "direction": key[2], "amount": 0.0, "transfers": 0})
        a["amount"] += e.get("traced_amount") or 0.0
        a["transfers"] += 1
    arrows = [merged[k] for k in sorted(merged)]
    titles = ["Funded the wallet" if c < 0 else "Traced wallet" if c == 0 else
              f"Hop {c}" for c in cols]
    return {"columns": titles, "rows": max([b["row"] for b in boxes], default=-1) + 1,
            "boxes": boxes, "arrows": arrows, "omitted": len(index) - len(boxes),
            "wallets": len(index), "transfers": len(case["graph"]["edges"]),
            "asset": case.get("asset")}
