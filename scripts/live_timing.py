"""Time live traces: wallets traced from the public chain APIs with an empty cache.

    python scripts/live_timing.py --chain tron --n 8 --out artifacts/live_timing.json

The six-chain benchmark (artifacts/benchmark_v1) recorded the seconds of each live trace
on five chains; its Tron traces were replayed from a cache, so Tron has no figure there.
This script takes a fixed sample (seed 26182) of that benchmark's own wallets for a
chain and traces each once, live, through the same rate limiter the server uses, into a
cache file that starts empty and is deleted afterwards. It writes what it measured and
nothing else: seconds and live requests per trace, with the date and the machine.
Network and the chain's API key (.env) are needed; no key is printed or written.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import random
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SEED = 26182


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--chain", default="tron")
    p.add_argument("--n", type=int, default=8)
    p.add_argument("--hops", type=int, default=3)
    p.add_argument("--out", default=str(ROOT / "artifacts" / "live_timing.json"))
    args = p.parse_args()
    if os.environ.get("OFFLINE") == "1":
        raise SystemExit("OFFLINE=1: a live trace cannot be timed offline")
    rows = list(csv.DictReader((ROOT / "artifacts" / "benchmark_v1" / args.chain
                                / "wallets.csv").open()))
    sample = random.Random(SEED).sample([r["wallet"] for r in rows], args.n)

    tmp = tempfile.mkdtemp(prefix="live-timing-")
    os.environ["VASPFUSION_CHAIN_CACHE"] = str(Path(tmp) / "cache.duckdb")
    from vaspfusion import cli
    traces = []
    for wallet in sample:
        start = time.perf_counter()
        try:
            case, fetcher = cli._run_case(wallet, args.chain, args.hops, str(ROOT / "data" / "labels.duckdb"))
            row = {"wallet": wallet, "seconds": round(time.perf_counter() - start, 2),
                   "live_requests": fetcher.stats["live"], "cached": fetcher.stats["hits"],
                   "outcome": case["outcome"], "wallets_read": len(case["graph"]["nodes"])}
        except Exception as e:  # noqa: BLE001 - a failed trace is reported, not hidden
            row = {"wallet": wallet, "seconds": round(time.perf_counter() - start, 2),
                   "error": f"{type(e).__name__}: {e}"[:200]}
        traces.append(row)
        print(row)
    good = [t for t in traces if "error" not in t]
    out_path = Path(args.out)
    doc = json.loads(out_path.read_text()) if out_path.exists() else {"chains": {}}
    doc["chains"][args.chain] = {
        "traces": len(good), "failed": len(traces) - len(good),
        "median_seconds": round(median(t["seconds"] for t in good), 2) if good else None,
        "min_seconds": min((t["seconds"] for t in good), default=None),
        "max_seconds": max((t["seconds"] for t in good), default=None),
        "median_live_requests": median(t["live_requests"] for t in good) if good else None,
        "max_hops": args.hops,
        "sample": f"{args.n} wallets drawn with seed {SEED} from artifacts/benchmark_v1/"
                  f"{args.chain}/wallets.csv",
        "chain_data": "fetched live into a cache that started empty; no replay",
        "measured_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "machine": f"{platform.system()} {platform.machine()}, {os.cpu_count()} cores, "
                   f"Python {platform.python_version()}",
        "per_trace": traces,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=1) + "\n")
    print(f"wrote {out_path}: {args.chain} median "
          f"{doc['chains'][args.chain]['median_seconds']} s over {len(good)} live traces")


if __name__ == "__main__":
    main()
