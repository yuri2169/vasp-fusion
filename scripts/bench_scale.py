"""Measure large-volume tracing on this machine (no network).

    python scripts/bench_scale.py [--rounds 25] [--workers 1,2,4,8] [--out artifacts/scale/metrics.json]

What is run: the recorded demo wallets (demo/cases.json), each replayed `--rounds` times
under different case ids, queued in a throwaway case store and traced by a pool of 1, 2, 4 and 8
worker processes (vaspfusion/workers.py), exactly as the server's pool traces a batch. Chain responses come from the demo cache (built from
tests/fixtures/demo by `make demo-cache`), so this times the tool, not a block explorer:
a live trace also waits on the public APIs' rate limits (docs/scaling.md).

What is written (every figure is from this run, with the machine it ran on):
* per worker count: cases per minute, median and 95th-percentile seconds per case,
  transfers analysed per second, peak memory, speed-up over one worker;
* where one case's time goes (one process, in order);
* how fast a batch upload is accepted and queued through the API;
* a check that every case, at every worker count, has the golden findings fingerprint.

`baseline` is the same replay measured before the queue and the pool existed
(artifacts/scale/baseline_before.json, taken on commit 619b06e); it is copied in, not
re-measured. The figures are a measurement of this machine at this moment and are not
checked by `make reproduce`.
"""
import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
import time
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASELINE = ROOT / "artifacts" / "scale" / "baseline_before.json"


def machine() -> str:
    return (f"{platform.system()} {platform.machine()}, {os.cpu_count()} cores, "
            f"Python {platform.python_version()}")


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[int(q * (len(ordered) - 1))]


# ------------------------------------------------------------------ where the time goes
def profile(specs: list[dict], cache: Path, label_db: Path, rounds: int) -> dict:
    """One process, one case after another: seconds per case and what they are spent on.
    Each bucket is the time spent in it and in nothing it calls that has its own bucket."""
    from vaspfusion import cases as C
    from vaspfusion import chains
    from vaspfusion.chains.cache import ChainCache, Fetcher
    from vaspfusion.labels.lookup import LabelStore
    from vaspfusion.store.cases import CaseStore
    from vaspfusion.trace import TraceConfig

    bucket: dict[str, float] = defaultdict(float)
    stack: list[list] = []
    undo = []

    def timed(owner, attr: str, name: str) -> None:
        fn = getattr(owner, attr)

        def wrapper(*a, **k):
            frame = [time.perf_counter(), 0.0]
            stack.append(frame)
            try:
                return fn(*a, **k)
            finally:
                stack.pop()
                took = time.perf_counter() - frame[0]
                bucket[name] += took - frame[1]
                if stack:
                    stack[-1][1] += took
        setattr(owner, attr, wrapper)
        undo.append((owner, attr, fn))

    timed(C, "trace", "the walk and the allocation")
    timed(C, "attribute", "attribution rules")
    timed(C, "add_counterfactuals", "counterfactual re-traces")
    timed(C, "add_leads", "deposit model on the trail")
    timed(C, "build_case", "assembling and validating the case")
    timed(Fetcher, "get_json", "chain responses: parse and check")
    timed(ChainCache, "get", "chain responses: read from the cache file")
    timed(LabelStore, "lookup_many", "label lookups")
    timed(LabelStore, "lookup", "label lookups")
    timed(CaseStore, "save", "storing the case")
    per_case: list[float] = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            store = CaseStore(Path(tmp) / "case.duckdb")
            for n in range(rounds + 1):
                if n == 1:                  # round 0 warms the imports and the model up
                    bucket.clear()
                    per_case.clear()
                    start = time.perf_counter()
                for spec in specs:
                    t0 = time.perf_counter()
                    fetcher = chains.cache_only_fetcher(cache)
                    cfg = TraceConfig(max_hops=spec.get("max_hops", 3))
                    provider = C.trace_provider(spec["chain"], fetcher, cfg)
                    with LabelStore(label_db) as labels:
                        detail = C.run_case(spec["address"], spec["chain"], provider, labels,
                                            case_id=f"p-{n}-{spec['id']}", cfg=cfg, fetcher=fetcher)
                    fetcher.close()
                    store.save(detail)
                    per_case.append(time.perf_counter() - t0)
            wall = time.perf_counter() - start
    finally:
        for owner, attr, fn in undo:
            setattr(owner, attr, fn)
    rest = wall - sum(bucket.values())
    return {"cases": len(per_case), "seconds": round(wall, 2),
            "cases_per_minute": round(len(per_case) / wall * 60, 1),
            "median_seconds_per_case": round(statistics.median(per_case), 3),
            "p95_seconds_per_case": round(pct(per_case, 0.95), 3),
            "where_the_time_goes": [
                {"part": k, "seconds": round(v, 2), "share": round(v / wall, 3)}
                for k, v in sorted({**bucket, "everything else": rest}.items(),
                                   key=lambda kv: -kv[1])]}


# ------------------------------------------------------------------ the worker pool
def pool_run(specs: list[dict], workers: int, rounds: int, cache: Path, label_db: Path,
             golden: dict) -> dict:
    """Queue every recorded wallet `rounds` times in a throwaway case store and let a
    pool of `workers` processes trace them, as the server's pool traces a batch."""
    from vaspfusion.api import main as api
    from vaspfusion.api import schemas as S
    from vaspfusion.cases import skeleton

    os.environ["VASPFUSION_CHAIN_CACHE"] = str(cache)      # the workers inherit it
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        api.CASE_DB, api.DESK_DB = tmp / "case.duckdb", tmp / "desk.duckdb"
        api.OUTBOX, api.LABEL_DB, api.WORKERS = tmp / "outbox", label_db, workers
        store, queue = api._cases(), api._queue()
        now = datetime.now(timezone.utc)
        ids = {}
        for n in range(rounds):
            for spec in specs:
                cid = f"bench-{n}-{spec['id']}"
                store.save(skeleton(S.CaseSummary(
                    id=cid, address=spec["address"], chain=spec["chain"], status="queued",
                    created_at=now, screening={"hit": False, "text": "-"}
                ).model_dump(mode="json")))
                ids[cid] = spec["id"]
        spawned = time.time()
        pool = api.start_pool(workers)
        try:
            while len(pool.pids) < workers and time.time() - spawned < 120:
                time.sleep(0.02)                # every worker started and warm
            ready = time.time()
            for cid in ids:                     # the batch arrives
                queue.enqueue(cid, {"max_hops": next(
                    s for s in specs if s["id"] == ids[cid]).get("max_hops", 3)})
            if not pool.drain(timeout=3600):
                raise SystemExit(f"{workers} workers: the queue did not empty in an hour")
        finally:
            api.stop_pool()
        jobs = queue.finished()
        bad = [j for j in jobs if j["state"] != "done" or j["attempts"] != 1]
        if len(jobs) != len(ids) or bad:
            raise SystemExit(f"{workers} workers: {len(jobs)} of {len(ids)} jobs closed, "
                             f"{len(bad)} not done at the first attempt: "
                             f"{[(j['case_id'], j['error']) for j in bad[:3]]}")
        same = 0
        for cid, case in store.get_many(list(ids)).items():
            want = golden.get(ids[cid], {}).get("findings_sha256")
            same += case["provenance"]["findings_sha256"] == want
    first = min(j["claimed_at"] for j in jobs)
    window = max(j["finished_at"] for j in jobs) - first
    # a case's time here is from the moment a worker was given it to the stored result
    seconds = [j["finished_at"] - j["claimed_at"] for j in jobs]
    by_pid: dict[int, list[dict]] = defaultdict(list)
    for j in jobs:
        by_pid[j["stats"]["pid"]].append(j)
    peaks = [max(j["stats"]["peak_mb"] or 0 for j in mine) for mine in by_pid.values()]
    return {
        "workers": workers, "cases": len(jobs), "seconds": round(window, 2),
        "cases_per_minute": round(len(jobs) / window * 60, 1),
        "median_seconds_per_case": round(statistics.median(seconds), 3),
        "p95_seconds_per_case": round(pct(seconds, 0.95), 3),
        "median_trace_seconds": round(statistics.median(
            j["stats"]["seconds"] for j in jobs), 3),
        "transfers_analysed": sum(j["stats"]["transfers_read"] for j in jobs),
        "transfers_per_second": round(sum(j["stats"]["transfers_read"] for j in jobs) / window, 1),
        "chain_responses_read": sum(j["stats"]["pages"] for j in jobs),
        "peak_memory_mb": round(sum(peaks), 1),
        "peak_memory_mb_per_worker": round(max(peaks), 1),
        "workers_that_traced": len(by_pid),
        "cases_per_worker": sorted(len(mine) for mine in by_pid.values()),
        "worker_startup_seconds": round(ready - spawned, 2),
        "golden_fingerprints_reproduced": f"{same} of {len(jobs)}",
    }


# ------------------------------------------------------------------ batch upload
def intake(label_db: Path, rows: int) -> dict:
    """Upload `rows` real labelled addresses as one batch through the API, on throwaway
    stores, with tracing left to workers that are not running: this times the intake
    alone (every row validated, screened, given a case and queued)."""
    import duckdb
    from fastapi.testclient import TestClient

    from vaspfusion.api import main as api
    con = duckdb.connect(str(label_db), read_only=True)
    found = con.execute("SELECT address FROM labels WHERE chain = 'tron' "
                        "ORDER BY address LIMIT ?", [rows]).fetchall()
    con.close()
    addresses = [r[0] for r in found]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        api.CASE_DB, api.DESK_DB = tmp / "case.duckdb", tmp / "desk.duckdb"
        api.WATCH_DB, api.AUDIT_DB = tmp / "watch.duckdb", tmp / "audit.duckdb"
        api.OUTBOX, api.OFFICERS = tmp / "outbox", tmp / "officers.json"
        api.AUTH_SECRET, api.LABEL_DB = tmp / "auth_secret", label_db
        api.WORKERS = 1                     # queued for workers; none is started here
        client = TestClient(api.app)
        text = "address,chain\n" + "".join(f"{a},tron\n" for a in addresses)
        start = time.perf_counter()
        r = client.post("/api/cases/batch", json={"csv": text})
        took = time.perf_counter() - start
        assert r.status_code == 202, r.text
        progress = r.json()["progress"]
        start = time.perf_counter()
        client.get(f"/api/batches/{r.json()['id']}")
        poll = time.perf_counter() - start
    if progress["queued"] != len(addresses):
        raise SystemExit(f"intake: {progress['queued']} of {len(addresses)} rows were queued")
    return {"rows": len(addresses), "seconds": round(took, 2),
            "rows_per_second": round(len(addresses) / took, 1),
            "progress_poll_seconds": round(poll, 3),
            "what": "one CSV upload of real labelled Tron addresses: every row validated, "
                    "screened against the threat tags, given a case and queued; none traced"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=25,
                    help="times each recorded wallet is replayed per run (default 25)")
    ap.add_argument("--workers", default="1,2,4,8")
    ap.add_argument("--intake-rows", type=int, default=500)
    ap.add_argument("--out", default=str(ROOT / "artifacts" / "scale" / "metrics.json"))
    ap.add_argument("--cache", default=str(ROOT / "data" / "demo_cache.duckdb"))
    ap.add_argument("--labels-db", default=str(ROOT / "data" / "labels.duckdb"))
    args = ap.parse_args()
    cache, label_db = Path(args.cache), Path(args.labels_db)
    for path, make in ((cache, "make demo-cache"), (label_db, "make labels")):
        if not path.exists():
            raise SystemExit(f"{path} is missing: run `{make}` first")
    warnings.simplefilter("ignore")
    os.environ["OFFLINE"] = "1"
    os.environ.setdefault("ETHERSCAN_API_KEY", "offline-replay")
    os.environ["VASPFUSION_AUTH"] = "off"
    specs = json.loads((ROOT / "demo" / "cases.json").read_text())["cases"]
    golden = json.loads((ROOT / "tests" / "golden" / "fingerprints.json").read_text())

    print(f"{len(specs)} recorded wallets x {args.rounds} rounds, on {machine()}")
    one = profile(specs, cache, label_db, rounds=min(args.rounds, 5))
    print(f"  one process, in order: {one['cases_per_minute']} cases/min, "
          f"median {one['median_seconds_per_case']} s")
    runs = []
    for w in [int(x) for x in args.workers.split(",")]:
        run = pool_run(specs, w, args.rounds, cache, label_db, golden)
        run["speedup"] = round(run["cases_per_minute"] / (runs[0] if runs else run)
                               ["cases_per_minute"], 2)
        runs.append(run)
        print(f"  {w} worker{'s' if w > 1 else ' '}: {run['cases_per_minute']:>7} cases/min  "
              f"median {run['median_seconds_per_case']} s  p95 {run['p95_seconds_per_case']} s  "
              f"{run['transfers_per_second']} transfers/s  {run['peak_memory_mb']} MB  "
              f"x{run['speedup']}  golden {run['golden_fingerprints_reproduced']}")
    taken = intake(label_db, args.intake_rows)
    print(f"  batch upload: {taken['rows']} rows queued in {taken['seconds']} s "
          f"({taken['rows_per_second']} rows/s)")
    out = {
        "measured_on": time.strftime("%Y-%m-%d"), "machine": machine(),
        "chain_data": "replayed from the recorded demo cache (tests/fixtures/demo); no network",
        "wallets": len(specs), "rounds": args.rounds, "runs": runs, "one_process": one,
        "intake": taken,
        "baseline": json.loads(BASELINE.read_text()) if BASELINE.exists() else None,
        "limits": [
            "Chain responses were replayed from a cache. A live trace waits on the public "
            "chain APIs, whose free keys are rate-limited; the limiter shares that limit "
            "between workers, so more workers do not make a live trace faster once the "
            "limit is reached. Live throughput was not measured.",
            "The case store and the queue are one DuckDB file with one writing process: "
            "the pool stores every result itself, one at a time.",
            "The recorded wallets are small traces (at most 9 wallets read each). Larger "
            "traces take longer per case.",
            "One machine. Nothing here was run on more than one host.",
        ],
        "notes": [
            "Cases per minute is counted from the first case handed to a worker to the last "
            "result stored, with the workers already started; their start-up (imports, the "
            "model) is reported beside it.",
            "A case's seconds run from the moment a worker is given it to its stored result.",
            "Transfers analysed are the transfers the traces read from the listings, "
            "counted once per case.",
            "Peak memory is the sum of every worker process's peak resident memory; the "
            "process that owns the store is not included.",
        ],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
