"""The recorded real demo wallets as finished cases, for the desk tests (no network)."""
import copy
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from demokit import SPECS, run_demo

NOW = datetime(2026, 10, 2, 9, 30, tzinfo=timezone.utc)
ROUTED = ("tron-coindcx", "tron-htx-coindcx", "eth-bitget")
UNROUTED = ("tron-abstain", "tron-ofac", "eth-bridge")


@lru_cache(maxsize=None)
def _case(case_id: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        return run_demo(case_id, Path(d) / "cache.duckdb", now=NOW,
                        meta={"case_ref": SPECS[case_id]["case_ref"]})


def demo_case(case_id: str) -> dict:
    return copy.deepcopy(_case(case_id))


def demo_cases(*case_ids: str) -> list[dict]:
    return [demo_case(c) for c in (case_ids or ROUTED + UNROUTED)]
