"""Rewrite tests/fixtures/demo/expected.json from the recorded fixtures (no network).

    python tests/refresh_expected.py

Run this only after a deliberate change to the trace or the rules, and read the
diff: every changed figure is a changed answer for a real wallet.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from demokit import FIX, SPECS, run_demo  # noqa: E402
from vaspfusion.cases import case_headline  # noqa: E402

if __name__ == "__main__":
    out = {}
    with tempfile.TemporaryDirectory() as d:
        for case_id in sorted(SPECS):
            out[case_id] = case_headline(run_demo(case_id, Path(d) / f"{case_id}.duckdb"))
    (FIX / "expected.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {len(out)} cases to {FIX / 'expected.json'}")
