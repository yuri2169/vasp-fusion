"""Re-take the demo wallets' label rows from a label DB, without the network.

    python scripts/refresh_demo_labels.py [--labels-db data/labels.duckdb]
    python tests/refresh_expected.py          # then rewrite the expected figures

Use it after the label DB changed (new derived deposit addresses, B4). Each demo
trace is replayed from its recorded responses (tests/fixtures/demo/<id>.json)
against the real label DB, and tests/fixtures/demo/labels.json is rewritten with
the rows the traces touched. If new labels make a trace ask for a page that was
never recorded, this stops: re-record that wallet with record_demo_fixtures.py.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests")]

from demokit import FIX, SPECS, demo_fetcher, demo_provider  # noqa: E402
from record_demo_fixtures import RecordingLabels  # noqa: E402
from vaspfusion.cases import run_case  # noqa: E402
from vaspfusion.labels.lookup import DEFAULT_DB, LabelStore  # noqa: E402
from vaspfusion.trace import TraceConfig  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels-db", default=str(DEFAULT_DB))
    args = ap.parse_args()
    seen: dict = {}
    with LabelStore(args.labels_db) as store, tempfile.TemporaryDirectory() as d:
        for case_id, spec in sorted(SPECS.items()):
            fetcher = demo_fetcher(Path(d) / f"{case_id}.duckdb", case_id)
            cfg = TraceConfig(max_hops=spec["max_hops"])
            case = run_case(spec["address"], spec["chain"],
                            demo_provider(spec["chain"], fetcher, cfg),
                            RecordingLabels(store, seen), case_id=case_id, cfg=cfg,
                            fetcher=fetcher, demo=True)
            print(f"{case_id}: {case['outcome']} top={case['top_vasp']} "
                  f"({fetcher.stats['live']} recorded pages replayed)")
    derived = sum(1 for r in seen.values() if r["tier"] == "derived")
    (FIX / "labels.json").write_text(json.dumps(
        {"_source": "rows of the label DB returned while tracing the demo wallets "
                    "(real labels; derived rows come from derived/*.csv)",
         "labels": dict(sorted(seen.items()))}, indent=1, sort_keys=True) + "\n")
    print(f"labels.json: {len(seen)} label rows, {derived} of them derived")


if __name__ == "__main__":
    main()
