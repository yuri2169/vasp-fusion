"""Rewrite tests/golden/ from the recorded demo fixtures (no network).

    python tests/refresh_golden.py

* fingerprints.json  per demo wallet: the findings fingerprint and the digest of the
  chain responses its trace read;
* <id>.txt           the case file of each demo wallet, as text.

Run this only after a deliberate change to the trace, the rules or the case file, and
read the diff: a changed fingerprint is a changed answer for a real wallet.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

GOLDEN = Path(__file__).resolve().parent / "golden"
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
COMMIT = "0" * 40          # the golden text must not change with every commit


def golden_case(case_id: str, cache_path) -> dict:
    """A demo wallet's case with the two things that change between runs pinned."""
    from demokit import SPECS, run_demo
    from vaspfusion import provenance as P
    before = os.environ.get("VASPFUSION_GIT_COMMIT")
    os.environ["VASPFUSION_GIT_COMMIT"] = COMMIT
    P.git_state.cache_clear()
    try:
        return run_demo(case_id, cache_path, now=NOW,
                        meta={"case_ref": SPECS[case_id].get("case_ref")})
    finally:
        if before is None:
            del os.environ["VASPFUSION_GIT_COMMIT"]
        else:
            os.environ["VASPFUSION_GIT_COMMIT"] = before
        P.git_state.cache_clear()


if __name__ == "__main__":
    from demokit import SPECS
    GOLDEN.mkdir(exist_ok=True)
    prints = {}
    with tempfile.TemporaryDirectory() as d:
        for case_id in sorted(SPECS):
            case = golden_case(case_id, Path(d) / f"{case_id}.duckdb")
            prints[case_id] = {k: case["provenance"][k]
                               for k in ("findings_sha256", "responses_sha256", "pages")}
            try:
                from vaspfusion.explain.case_file import case_file_text
            except ImportError:           # the case file is built after the receipt
                continue
            (GOLDEN / f"{case_id}.txt").write_text(case_file_text(case))
    (GOLDEN / "fingerprints.json").write_text(json.dumps(prints, indent=1) + "\n")
    print(f"wrote {len(prints)} cases to {GOLDEN}")
