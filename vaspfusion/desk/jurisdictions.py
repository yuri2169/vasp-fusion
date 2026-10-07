"""Where traced money ended up, by the country each exchange is registered in.

The country is the directory's cited `jurisdiction` and nothing else: an exchange the
directory holds no cited country for is listed apart, never placed. This says where an
exchange is registered, not where a suspect is (nothing here knows that).

Counted from the same wallets the request desk routes (routing.routed_wallets): a wallet
of a finished case whose money reached a named exchange at or above the bar. An amount is
in dollars only for a dollar stablecoin; other assets add to the counts, not the sum.
"""
from __future__ import annotations

from .routing import routed_wallets

BASIS = "Where the exchange is registered, not where the suspect is."


def _exchange(name: str, wallets: list[dict], entry: dict) -> dict:
    return {"vasp": name,
            "total_usd": round(sum(w["amount_usd"] or 0.0 for w in wallets), 2),
            "wallets": len(wallets),
            "unpriced_wallets": sum(1 for w in wallets if w["amount_usd"] is None),
            "case_ids": sorted({w["case_id"] for w in wallets}),
            "fiu_ind_registered": entry["fiu_ind_registered"],
            "fiu_ind_as_of": entry["fiu_ind_as_of"],
            "source_urls": [s["url"] for s in entry["sources"] if s["field"] == "jurisdiction"]}


def destinations(cases: list[dict], directory) -> dict:
    """`DestinationsByJurisdiction` for these cases (one case: pass a list of one)."""
    by_vasp: dict[str, list[dict]] = {}
    for case in cases:
        for w in routed_wallets(case, canonical=directory.canonical):
            by_vasp.setdefault(w["vasp"], []).append(w)
    places: dict[str, list[dict]] = {}
    unplaced = []
    for name in sorted(by_vasp):
        entry = directory.get(name)
        row = _exchange(name, by_vasp[name], entry)
        if entry["jurisdiction"]:
            places.setdefault(entry["jurisdiction"], []).append(row)
        else:
            unplaced.append(row)

    def by_amount(rows: list[dict]) -> list[dict]:
        return sorted(rows, key=lambda r: (-r["total_usd"], r["vasp"]))

    out = [{"jurisdiction": place,
            "total_usd": round(sum(r["total_usd"] for r in rows), 2),
            "wallets": sum(r["wallets"] for r in rows),
            "unpriced_wallets": sum(r["unpriced_wallets"] for r in rows),
            "case_ids": sorted({c for r in rows for c in r["case_ids"]}),
            "exchanges": by_amount(rows)} for place, rows in places.items()]
    out.sort(key=lambda p: (-p["total_usd"], p["jurisdiction"]))
    return {"basis": BASIS, "places": out, "not_on_record": by_amount(unplaced)}
