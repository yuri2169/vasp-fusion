"""Rewrite the `expected` blocks of the discovery fixtures from the recorded responses.
No network. Run it only after a deliberate change to the rules, and read the diff.

    python tests/refresh_discover_expected.py
"""
import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
os.environ.pop("OFFLINE", None)
os.environ["TRONGRID_API_KEY"] = ""

from discoverkit import FIX, FixtureLabels, load, replay_fetcher  # noqa: E402
from vaspfusion.chains.evm import EvmProvider  # noqa: E402
from vaspfusion.chains.tron import TronProvider  # noqa: E402
from vaspfusion.discover.crawl import CrawlConfig, discover  # noqa: E402
from vaspfusion.discover.evaluate import EvalConfig, evaluate  # noqa: E402


def save(name: str, expected: dict) -> None:
    doc = load(name)
    doc["expected"] = expected
    (FIX / f"{name}.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(f"{name}.json: expected rewritten")


with tempfile.TemporaryDirectory() as d:
    fetcher = replay_fetcher(Path(d), "crawl_tron")
    cfg = CrawlConfig(seed_limit=200, max_candidates=5, entities=("CoinDCX", "KuCoin"))
    result = discover("tron", TronProvider(fetcher, page_size=200, max_pages=1, key=""),
                      TronProvider(fetcher, page_size=50, max_pages=1, key=""),
                      FixtureLabels("crawl_tron"), cfg)
    save("crawl_tron", {"findings": [asdict(f) for f in result.findings],
                        "stats": result.stats, "totals": result.totals})

with tempfile.TemporaryDirectory() as d:
    fix = load("holdout_eth")
    cfg = EvalConfig(n_positive=6, n_negative=6, limit=50)
    provider = EvmProvider("ethereum", replay_fetcher(Path(d), "holdout_eth"),
                           page_size=cfg.limit, max_pages=1, key="test-key")
    g = fix["groups"]
    report = evaluate(provider, FixtureLabels("holdout_eth"), g["positives"],
                      g["neg_exchange"], g["neg_other"], cfg)
    save("holdout_eth", {"metrics": report.metrics, "rows": report.rows})
