"""Freeze marks on a served case: which of its wallets Tether has frozen (USDT's blacklist,
labels/frozen.py), and where each sits: the case's own wallet, the Hop Rail's path, or
elsewhere in the traced graph.

Worked out each time a case is read, from the stored graph and the freeze snapshot, and
never stored with the case (like its risk): no digest or fingerprint moves, and a newer
snapshot marks every case at once. A mark says the issuer froze that address on that
date. It does not give the reason, and says nothing about anyone who dealt with it.
"""
from __future__ import annotations

from .labels.frozen import FreezeList, mark_text

WHERE_ORDER = {"origin": 0, "path": 1, "graph": 2}


def case_freezes(case: dict, freeze_list: FreezeList | None = None) -> list[dict]:
    fl = freeze_list or FreezeList.load()
    if not fl.rows:
        return []
    graph = case.get("graph") or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    on_path = {a for h in case.get("hop_rail") or []
               for a in (h.get("from_address"), h.get("to_address"))}
    seen: set[tuple[str, str]] = set()
    marks: list[dict] = []

    def add(node_id: str, address: str, chain: str, where: str, side: str, hop: int,
            amount: float, asset: str | None, hashes: list[str]) -> None:
        if (address, chain) in seen:
            return
        hit = fl.lookup(address, chain)
        if hit is None:
            return
        seen.add((address, chain))
        marks.append({"id": node_id, "address": address, "chain": chain, "where": where,
                      "side": side, "tx_hashes": sorted(set(hashes)),
                      "hop": hop, "amount": round(amount, 6), "asset": asset,
                      "issuer": hit["issuer"], "frozen_asset": hit["asset"],
                      "frozen_at": hit["frozen_at"], "tx_hash": hit["tx_hash"],
                      "contract": hit["contract"], "text": mark_text(hit)})

    chain = case.get("chain")
    if chain is None or not case.get("address"):
        return []                       # not a case this can place on a chain
    add(case["address"], case["address"], chain, "origin", "origin", 0,
        case.get("total_sent") or 0.0, case.get("asset"), [])
    for n in nodes:
        if n.get("role") == "suspect":
            continue
        into = [e for e in edges if e["target"] == n["id"] and e["direction"] == "outbound"]
        out_of = [e for e in edges if e["source"] == n["id"] and e["direction"] == "inbound"]
        side = "outbound" if into or not out_of else "inbound"
        moved = into if side == "outbound" else out_of
        address = n.get("address") or n["id"].rpartition(":")[2]
        add(n["id"], address, n.get("chain") or chain,
            "path" if address in on_path else "graph", side, n.get("hop") or 0,
            float(sum(e.get("traced_amount") or 0.0 for e in moved)),
            (moved[0].get("asset") if moved else None) or case.get("asset"),
            [e["tx_hash"] for e in moved if e.get("tx_hash")])
    return sorted(marks, key=lambda m: (WHERE_ORDER[m["where"]], m["hop"], m["chain"],
                                        m["address"]))
