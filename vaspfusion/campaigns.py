"""Complaints that may be one operation: wallets that the traces of different suspect
wallets both reached.

Read from stored traces only (no chain request). A wallet counts when two or more cases
on the same chain, whose suspect wallets differ, reach it: as an intermediary on their
trail, or as the suspect wallet of one of them. Each link names the cases, how far each
was from the wallet and how much of its money arrived.

What proves nothing is left out: an exchange's, custodial or swap service's wallet, a
bridge, a mixer, a DeFi contract and any other wallet a label names (a labelled public
contract). Two victims whose money both reached one exchange's hot wallet share an
exchange, not an offender. A wallet whose only label is a warning (a threat tag, a scam
or sanctions list) stays in, as does one the issuer of USDT froze, and the link says
which. A busy unlabelled wallet (the trace's hub: very many counterparties) stays in too
but is marked: it is most likely a service, and it is listed after the others.

The limit, said wherever this is shown: an unlabelled public contract or service can
appear as a shared wallet, so read a link with its amounts.
"""
from __future__ import annotations

from .labels.frozen import FreezeList, mark_text
from .labels.threats import named as threat_named
from .labels.threats import tag_of

# label categories that name a service or a public contract: a shared one proves nothing
SERVICE_CATEGORIES = {"exchange", "custodial_wallet", "swap_service", "bridge", "mixer",
                      "defi", "entity"}
WARNING_CATEGORIES = {"scam": "on a scam list", "sanctioned": "on a sanctions list"}
LIMIT = ("A shared wallet is a lead, not proof of one operation: an unlabelled public "
         "contract or service can appear as one, so read a link with its amounts. Exchange, "
         "bridge, mixer, swap-service and other labelled wallets are left out.")


def _warning(label: dict | None) -> list[str]:
    """The warning flags a label carries, in words; [] for none."""
    if not label:
        return []
    out = []
    tag = tag_of(label)
    if tag is not None:
        out.append(f"tagged {threat_named(tag)}")
    if label.get("category") in WARNING_CATEGORIES and not tag:
        out.append(f"{WARNING_CATEGORIES[label['category']]} ({label.get('entity')})")
    return out


def _kept(label: dict | None) -> bool:
    """Whether a wallet with this label can link complaints."""
    if not label:
        return True
    return bool(_warning(label)) or label.get("category") not in SERVICE_CATEGORIES


def reached(case: dict) -> dict[tuple[str, str], dict]:
    """(chain, address) -> what this case's trace says of each wallet it reached on its way
    out, and of its own suspect wallet."""
    graph = case.get("graph") or {}
    edges = [e for e in graph.get("edges") or [] if e.get("direction") == "outbound"]
    out: dict[tuple[str, str], dict] = {}
    out[(case["chain"], case["address"])] = {
        "hop": 0, "amount": case.get("total_sent") or 0.0, "asset": case.get("asset"),
        "first_arrival": None, "label": None, "busy": False, "suspect": True}
    for n in graph.get("nodes") or []:
        if n.get("role") == "suspect":
            continue
        into = sorted((e for e in edges if e["target"] == n["id"]),
                      key=lambda e: (str(e["block_time"]), e["tx_hash"]))
        if not into:
            continue                        # a funder only: not reached by the money
        address = n.get("address") or n["id"].rpartition(":")[2]
        out[(n.get("chain") or case["chain"], address)] = {
            "hop": n.get("hop"), "amount": round(sum(e["traced_amount"] for e in into), 6),
            "asset": into[0].get("asset"), "first_arrival": into[0]["block_time"],
            "label": n.get("label"), "busy": bool(n.get("is_hub")), "suspect": False}
    return out


def linked(cases: list[dict], freeze_list: FreezeList | None = None) -> list[dict]:
    """Every wallet two or more different suspect wallets' traces reached, with the cases."""
    fl = freeze_list or FreezeList.load()
    by: dict[tuple[str, str], list[tuple[dict, dict]]] = {}
    for case in cases:
        if case.get("status") != "done":
            continue
        for key, seen in reached(case).items():
            by.setdefault(key, []).append((case, seen))
    links = []
    for (chain, address), hits in by.items():
        suspects = {(c["chain"], c["address"]) for c, _ in hits}
        if len(suspects) < 2 or not any(not s["suspect"] for _, s in hits):
            continue
        label = next((s["label"] for _, s in hits if s["label"]), None)
        if not _kept(label):
            continue
        flags = _warning(label)
        frozen = fl.lookup(address, chain)
        if frozen:
            flags.append(mark_text(frozen))
        rows = sorted(({"case_id": c["id"], "case_ref": c.get("case_ref"),
                        "suspect": c["address"], "hop": s["hop"], "amount": s["amount"],
                        "asset": s["asset"], "first_arrival": s["first_arrival"],
                        "is_suspect": s["suspect"]} for c, s in hits),
                      key=lambda r: (r["hop"], -r["amount"], r["case_id"]))
        links.append({
            "address": address, "chain": chain, "label": (label or {}).get("label")
            or (label or {}).get("entity"), "flags": flags,
            "busy": any(s["busy"] for _, s in hits),
            "suspects": len(suspects), "cases": rows,
        })
    return sorted(links, key=lambda k: (k["busy"], -k["suspects"], -sum(
        r["amount"] for r in k["cases"] if not r["is_suspect"]), k["chain"], k["address"]))


def related(case_id: str, cases: list[dict], freeze_list: FreezeList | None = None) -> list[dict]:
    """The links one case is part of."""
    return [k for k in linked(cases, freeze_list)
            if any(r["case_id"] == case_id for r in k["cases"])]
