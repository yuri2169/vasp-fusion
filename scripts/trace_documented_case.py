"""Trace every address of a publicly documented case and write what the tool found.

    python scripts/trace_documented_case.py data/validation/wazirx_2024.json

The file names the case, its sources, and how its addresses are taken from the label
store (an entity name: the explorer's public tags). Each address is traced with the
pipeline a case runs, at the interface's defaults, twice over: with every label, and with
the labels of the case's own entity hidden (what the trace finds when nobody has tagged
the thief's wallets yet). Nothing is tuned and no address is left out.

Writes artifacts/<case id>/trace_table.json. `--offline` replays from the cache.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vaspfusion import chains  # noqa: E402
from vaspfusion import risk as R  # noqa: E402
from vaspfusion.chains.ratelimit import RateLimiter  # noqa: E402
from vaspfusion.eval.risk_validation import trace_wallet  # noqa: E402
from vaspfusion.labels.lookup import LabelStore  # noqa: E402

VIEWS = {"as_shown": "every label", "entity_hidden": "the case's own tags hidden"}


def row_of(view: dict) -> dict:
    if "error" in view:
        return {"error": view["error"]}
    risk = R.case_risk(view)
    return {"outcome": view["outcome"], "asset": view["asset"], "total_sent": view["total_sent"],
            "wallets": len(view["graph"]["nodes"]), "transfers": len(view["graph"]["edges"]),
            "exchanges": [{"vasp": c["vasp"], "direction": c["direction"], "hops": c["hops"],
                           "confidence": c["confidence"]} for c in view["candidates"]],
            "where_funds_went": view["where_funds_went"],
            "flags": sorted({f["code"] for f in view["typology_flags"]}),
            "risk_score": risk["score"] if risk else None,
            "risk_class": risk["risk_class"] if risk else None}


def tally(rows: list[dict], view: str) -> dict:
    out: dict[str, int] = {}
    for r in rows:
        v = r[view]
        if "error" in v:
            key = "could not be read"
        elif v["outcome"] == "ATTRIBUTED":
            key = "an exchange named"
        elif v["outcome"] == "SANCTIONED_OR_MIXER_REACHED":
            key = "reached a mixer or a sanctioned address"
        elif v["asset"] is None:
            key = "nothing to trace"
        else:
            top = max(v["where_funds_went"], key=lambda s: s["share"], default=None)
            key = "insufficient evidence: most funds " + {
                "other_label": "stopped at a wallet with a non-exchange label",
                "hub": "stopped at an unlabelled high-activity wallet",
                "bridge": "went into a bridge", "not_moved": "did not move on",
                "beyond_hop_limit": "went beyond the hop limit",
            }.get(top["kind"] if top else "", f"ended as '{top['kind'] if top else 'nothing'}'")
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("case")
    ap.add_argument("--labels-db", default=str(ROOT / "data" / "labels.duckdb"))
    ap.add_argument("--cache", default=str(ROOT / "data" / "documented_cache.duckdb"))
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    doc = json.loads(Path(args.case).read_text())
    if args.offline:
        fetcher = chains.Fetcher(chains.ChainCache(args.cache, read_only=True), offline=True)
    else:
        fetcher = chains.Fetcher(chains.ChainCache(args.cache, hold=True),
                                 chains.UrllibTransport(), limiter=RateLimiter())
    rows = []
    with LabelStore(args.labels_db) as store:
        for a in doc["addresses"]:
            traced = trace_wallet({"address": a["address"], "chain": doc["chain"]}, fetcher, store)
            row = {"address": a["address"], "tag": a["tag"],
                   **{v: row_of(traced["views"][v]) for v in VIEWS}}
            rows.append(row)
            print(f"  {a['tag']:<22}" + "  |  ".join(
                f"{row[v].get('outcome', 'could not be read')}" for v in VIEWS),
                file=sys.stderr, flush=True)
    out = ROOT / "artifacts" / doc["id"] / "trace_table.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    table = {"case": doc["id"], "title": doc["title"], "chain": doc["chain"],
             "trace": {"max_hops": 3, "max_wallets": 40, "inbound_hops": 1, "since": None},
             "addresses": len(rows), "views": VIEWS,
             "summary": {v: tally(rows, v) for v in VIEWS}, "rows": rows}
    out.write_text(json.dumps(table, indent=1) + "\n")
    for v, words in VIEWS.items():
        print(f"{words}:")
        for k, n in table["summary"][v].items():
            print(f"  {n:>3} of {len(rows)}  {k}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
