"""Measure the SAHYOG intake end to end on the recorded wallets (no network).

    python scripts/intake_timing.py [--out artifacts/intake_timing.json]

One complaint carrying every recorded demo wallet (demo/cases.json) is posted to
POST /api/sahyog/complaints on throwaway stores. The clock runs from the POST until
every wallet has its result (traced, attributed, counterfactual checked, scored, risk
classified, result handed to the gateway). Chain responses come from the demo cache
(built from tests/fixtures/demo), so this times the tool, not a block explorer: a live
trace also waits on the public APIs' rate limits.

The figure is a measurement on this machine at this moment. It is printed with the
machine it was taken on and is not checked by `make reproduce`.
"""
import argparse
import json
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="also write the measurement as JSON here")
    ap.add_argument("--cache", default=str(ROOT / "data" / "demo_cache.duckdb"),
                    help="the demo chain cache (`make demo-cache` builds it)")
    args = ap.parse_args()
    cache = Path(os.environ.get("VASPFUSION_CHAIN_CACHE") or args.cache)
    if not cache.exists():
        raise SystemExit(f"{cache} is missing: run `make demo-cache` first")
    os.environ["OFFLINE"] = "1"
    os.environ.setdefault("ETHERSCAN_API_KEY", "offline-replay")
    os.environ["VASPFUSION_AUTH"] = "off"
    os.environ["SAHYOG_API_KEY"] = "timing-run-key"

    from fastapi.testclient import TestClient

    from vaspfusion import chains
    from vaspfusion.api import main as api

    specs = json.loads((ROOT / "demo" / "cases.json").read_text())["cases"]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        api.CASE_DB, api.DESK_DB = tmp / "case.duckdb", tmp / "desk.duckdb"
        api.WATCH_DB, api.AUDIT_DB = tmp / "watch.duckdb", tmp / "audit.duckdb"
        api.OUTBOX, api.OFFICERS = tmp / "outbox", tmp / "officers.json"
        api.AUTH_SECRET = tmp / "auth_secret"
        api.make_fetcher = lambda: chains.cache_only_fetcher(cache)
        client = TestClient(api.app)
        key = {"X-SAHYOG-Key": "timing-run-key"}
        body = {"complaint_ref": "TIMING-0001", "agency": "timing run", "officer": "timing run",
                "wallets": [{"address": s["address"], "chain": s["chain"]} for s in specs]}
        start = time.perf_counter()
        # the test client returns once the background queue has run: every wallet is traced
        r = client.post("/api/sahyog/complaints", json=body, headers=key)
        status = client.get("/api/sahyog/complaints/TIMING-0001", headers=key).json()
        elapsed = time.perf_counter() - start
        assert r.status_code == 202, r.text
        wallets = status["wallets"]
        if status["status"] != "result" or any(w["status"] != "result" for w in wallets):
            raise SystemExit(f"not every wallet finished: {[w['status'] for w in wallets]}")
        results = sorted((tmp / "outbox" / "results").glob("*.json"))
        transfers = pages = 0
        for w in wallets:
            case = client.get(f"/api/cases/{w['case_id']}").json()
            transfers += len(case["graph"]["edges"])
            pages += case["provenance"].get("pages") or 0
    out = {
        "wallets": len(wallets), "seconds": round(elapsed, 2),
        "seconds_per_wallet": round(elapsed / len(wallets), 2),
        "transfers_in_the_results": transfers, "chain_responses_read": pages,
        "results_handed_to_the_gateway": len(results),
        "outcomes": {o: sum(1 for w in wallets if w["outcome"] == o)
                     for o in sorted({w["outcome"] for w in wallets})},
        "chain_data": "replayed from the recorded demo cache; no network",
        "machine": f"{platform.system()} {platform.machine()}, {os.cpu_count()} cores, "
                   f"Python {platform.python_version()}",
        "measured_on": time.strftime("%Y-%m-%d"),
    }
    print(json.dumps(out, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
