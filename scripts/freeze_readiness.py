"""Measure the part of a freeze this tool controls: from a complaint arriving to a
freezing request standing ready for the officer's signature (no network).

    python scripts/freeze_readiness.py [--out artifacts/freeze_readiness.json]

One complaint carrying every recorded demo wallet (demo/cases.json) is posted to the
intake on throwaway stores. When its wallets have their results, one request per
exchange the cases route to is drafted (know-your-customer records and a freeze), and
its letter is rendered. The clock runs from the complaint's POST until the last letter
is in hand: at that point nothing is left to do but an officer reading and approving.

**No freeze was made and none was timed.** No request of ours can reach an exchange:
what happens after the officer signs (the portal, the exchange's own handling) is
outside this tool and outside this measurement. Chain responses are replayed from the
demo cache, so this times the tool, not a block explorer; the seconds a live trace
waits on the public chain APIs are measured separately (artifacts/benchmark_v1,
artifacts/live_timing.json) and are not added in here.
"""
import argparse
import json
import os
import platform
import sys
import tempfile
import time
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="also write the measurement as JSON here")
    ap.add_argument("--cache", default=str(ROOT / "data" / "demo_cache.duckdb"),
                    help="the demo chain cache (`make demo-cache` builds it)")
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    cache = Path(os.environ.get("VASPFUSION_CHAIN_CACHE") or args.cache)
    if not cache.exists():
        raise SystemExit(f"{cache} is missing: run `make demo-cache` first")
    os.environ["OFFLINE"] = "1"
    os.environ.setdefault("ETHERSCAN_API_KEY", "offline-replay")
    os.environ["VASPFUSION_AUTH"] = "off"
    os.environ["SAHYOG_API_KEY"] = "timing-run-key"
    for name in ("SAHYOG_URL", "SAHYOG_SIGNING_SECRET"):
        os.environ.pop(name, None)

    from fastapi.testclient import TestClient

    from vaspfusion import chains
    from vaspfusion.api import main as api

    specs = json.loads((ROOT / "demo" / "cases.json").read_text())["cases"]
    key = {"X-SAHYOG-Key": "timing-run-key"}
    runs = []
    for n in range(args.runs):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            api.CASE_DB, api.DESK_DB = tmp / "case.duckdb", tmp / "desk.duckdb"
            api.WATCH_DB, api.AUDIT_DB = tmp / "watch.duckdb", tmp / "audit.duckdb"
            api.OUTBOX, api.OFFICERS = tmp / "outbox", tmp / "officers.json"
            api.AUTH_SECRET, api.SAHYOG_SECRET = tmp / "auth_secret", tmp / "no-secret"
            api.make_fetcher = lambda: chains.cache_only_fetcher(cache)
            client = TestClient(api.app)
            body = {"complaint_ref": f"FREEZE-{n:04d}", "agency": "timing run",
                    "officer": "timing run",
                    "wallets": [{"address": s["address"], "chain": s["chain"]} for s in specs]}
            start = time.perf_counter()
            r = client.post("/api/sahyog/complaints", json=body, headers=key)
            assert r.status_code == 202, r.text
            status = client.get(f"/api/sahyog/complaints/FREEZE-{n:04d}", headers=key).json()
            if any(w["status"] != "result" for w in status["wallets"]):
                raise SystemExit("not every wallet finished")
            results_at = time.perf_counter() - start
            drafts, letters = [], 0
            for row in client.get("/api/desk").json()["rows"]:
                t0 = time.perf_counter()
                made = client.post("/api/requests", json={
                    "vasp": row["vasp"], "case_ids": row["case_ids"],
                    "asks": ["kyc", "freeze"], "officer": "timing run"})
                if made.status_code != 201:      # the evidence does not support a request
                    continue
                req = made.json()
                pdf = client.get(f"/api/requests/{req['id']}/pdf")
                assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
                letters += len(pdf.content)
                assert req["status"] == "drafted" and "freeze" in req["letter"]["asks"]
                drafts.append({"vasp": row["vasp"], "wallets": len(req["letter"]["wallets"]),
                               "seconds": round(time.perf_counter() - t0, 3)})
            ready_at = time.perf_counter() - start
            runs.append({"seconds_to_results": round(results_at, 2),
                         "seconds_to_requests_ready": round(ready_at, 2), "requests": drafts})
    last = runs[-1]
    out = {
        "what": "From a complaint's POST to a freezing request drafted with its letter for "
                "each exchange its wallets route to: ready for the officer's signature.",
        "not_measured": "No freeze was made or timed. Nothing here went to an exchange or "
                        "to the SAHYOG portal; what happens after the officer approves is "
                        "outside this tool.",
        "wallets": len(specs), "runs": len(runs),
        "seconds_to_results": median(r["seconds_to_results"] for r in runs),
        "seconds_to_requests_ready": median(r["seconds_to_requests_ready"] for r in runs),
        "all_runs_seconds_to_requests_ready": [r["seconds_to_requests_ready"] for r in runs],
        "requests_drafted": len(last["requests"]),
        "exchanges": [d["vasp"] for d in last["requests"]],
        "wallets_asked_about": sum(d["wallets"] for d in last["requests"]),
        "median_seconds_to_draft_one_request": round(
            median(d["seconds"] for r in runs for d in r["requests"]), 3),
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
