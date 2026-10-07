"""Record a real wallet whose money left its chain through a bridge, for offline replay.

    python scripts/record_crosschain_case.py            # network and the chain keys in .env

Traces the wallet live (three hops) and writes everything the trace read to
tests/fixtures/crosschain/<id>.json: every chain and bridge-index response, and every
label row the label store returned. tests/test_stargate_case.py replays it with no
network. What the trace found about each bridge deposit is written to
artifacts/crosschain/<id>.json, as measured: nothing in it is typed in.

The wallet is not a demo case and nothing is claimed about its owner: it was picked on
8 Oct 2026 from recent deposits into Stargate's USDT pool on Ethereum because most of
what it sent went through the bridge.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from record_demo_fixtures import RecordingLabels, RecordingTransport, _secrets  # noqa: E402
from vaspfusion.cases import run_case, trace_provider  # noqa: E402
from vaspfusion.chains.cache import ChainCache, Fetcher  # noqa: E402
from vaspfusion.labels.lookup import LabelStore  # noqa: E402
from vaspfusion.trace import TraceConfig  # noqa: E402

CASES = [{"id": "eth-stargate", "chain": "ethereum", "max_hops": 3,
          "address": "0xd652d8bc3d851b18d045b9c9bbb83d1001af5ea3"}]
OUT = ROOT / "tests" / "fixtures" / "crosschain"
ART = ROOT / "artifacts" / "crosschain"


def summary(case: dict) -> dict:
    keep = ("bridge", "status", "source_chain", "source_tx", "dest_name", "recipient",
            "payout_tx", "asset_in", "amount_in", "asset_out", "amount_out", "fee", "seconds",
            "matched_by", "reason")
    return {"address": case["address"], "chain": case["chain"], "chains": case["chains"],
            "asset": case["asset"], "outcome": case["outcome"], "top_vasp": case["top_vasp"],
            "crossings": [{k: c.get(k) for k in keep} for c in case["crossings"]],
            "where_funds_went": [{k: w.get(k) for k in ("kind", "share", "text")}
                                 for w in case["where_funds_went"]],
            "narrative": case["narrative"]}


def main() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with LabelStore() as store:
        for spec in CASES:
            rec, seen = RecordingTransport(), {}
            with tempfile.TemporaryDirectory() as d:
                fetcher = Fetcher(ChainCache(Path(d) / "c.duckdb"), rec, offline=False)
                cfg = TraceConfig(max_hops=spec["max_hops"])
                case = run_case(spec["address"], spec["chain"],
                                trace_provider(spec["chain"], fetcher, cfg),
                                RecordingLabels(store, seen), case_id=spec["id"], cfg=cfg,
                                fetcher=fetcher,
                                now=datetime(2026, 10, 8, tzinfo=timezone.utc))
            doc = {"_source": f"{spec['chain']} trace of {spec['address']}, max_hops="
                              f"{cfg.max_hops}, live APIs", "_recorded": today,
                   "responses": rec.responses, "labels": dict(sorted(seen.items()))}
            text = json.dumps(doc, indent=1, sort_keys=True) + "\n"
            for secret in _secrets():
                assert secret not in text, f"an API key leaked into fixture {spec['id']}"
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / f"{spec['id']}.json").write_text(text)
            ART.mkdir(parents=True, exist_ok=True)
            (ART / f"{spec['id']}.json").write_text(json.dumps(
                {"recorded": today, "max_hops": cfg.max_hops, **summary(case)}, indent=1) + "\n")
            followed = [c for c in case["crossings"] if c["status"] == "followed"]
            print(f"{spec['id']}: {len(rec.responses)} responses, {len(text) // 1024} KB, "
                  f"{len(seen)} label rows, {case['outcome']}, chains {case['chains']}, "
                  f"{len(followed)} of {len(case['crossings'])} bridge deposits followed")


if __name__ == "__main__":
    main()
