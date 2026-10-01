"""Record real responses for the discovery tests (run once, commit the JSON).

    python scripts/record_discover_fixtures.py gas      # raw listings of two deposit addresses
    python scripts/record_discover_fixtures.py crawl    # a small real crawl (see CRAWL)
    python scripts/record_discover_fixtures.py holdout  # a few tagged Ethereum addresses

Writes tests/fixtures/discover/<name>.json: every request made (keyed by
request_key(), API keys stripped) with the untouched response body, plus the real
label rows the run touched. Tests replay these and never reach the network.
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

from record_chain_fixtures import RecordingTransport, _secrets  # noqa: E402
from vaspfusion.chains.cache import ChainCache, Fetcher  # noqa: E402
from vaspfusion.chains.tron import TronProvider  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "discover"
SINCE = datetime(2026, 9, 17, tzinfo=timezone.utc)
# Two real deposit addresses seen sweeping on 24 Sep 2026: KuCoin's gets an energy
# delegation and a TRX top-up from labelled KuCoin wallets, CoinDCX's a TRX top-up.
GAS = {"kucoin": "TD9MoA86kzLmYBENwHNjDN4vmFpXMZjBT7",
       "coindcx": "TTTZH6nWX8tk1b73xHfCJk3x9aBRgWbeEK"}


def _write(name: str, source: str, rec: RecordingTransport, **extra) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    doc = {"_source": source, "_recorded": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
           **extra, "responses": rec.responses}
    text = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    for secret in _secrets():
        assert secret not in text, f"an API key leaked into fixture {name}"
    (OUT / f"{name}.json").write_text(text)
    print(f"{name}.json: {len(rec.responses)} responses, {len(text) // 1024} KB")


def record_gas() -> None:
    rec = RecordingTransport()
    with tempfile.TemporaryDirectory() as d:
        fetcher = Fetcher(ChainCache(Path(d) / "c.duckdb"), rec, offline=False)
        provider = TronProvider(fetcher, page_size=50, max_pages=1)
        for address in GAS.values():
            provider.gas_events(address, since=SINCE)
    _write("tron_gas", "TronGrid raw listings since 2026-09-17 of " + ", ".join(GAS.values()), rec)


class RecordingLabels:
    """The real label store, remembering every row it returned."""

    def __init__(self, store, entities=None):
        self.store, self.entities, self.seen = store, entities, {}

    def _keep(self, chain, label):
        self.seen[f"{chain}:{label.address}"] = {"query_chain": chain, **label.as_dict()}

    def seeds(self, chain):
        seeds = [s for s in self.store.seeds(chain)
                 if self.entities is None or s.entity in self.entities]
        for s in seeds:
            self._keep(chain, s)
        return seeds

    def lookup_many(self, pairs):
        found = self.store.lookup_many(pairs)
        for (_, chain), label in found.items():
            self._keep(chain, label)
        return found


def crawl_providers(fetcher, cfg):
    """The two Tron providers a crawl uses (the tests build the same pair)."""
    return (TronProvider(fetcher, page_size=200, max_pages=cfg.seed_limit // 200),
            TronProvider(fetcher, page_size=cfg.candidate_limit, max_pages=1))


def record_crawl() -> None:
    """A small real crawl: CoinDCX and KuCoin, the first 5 senders per wallet."""
    from dataclasses import asdict

    from vaspfusion.discover.crawl import CrawlConfig, discover
    from vaspfusion.labels.lookup import LabelStore

    cfg = CrawlConfig(seed_limit=200, max_candidates=5, entities=("CoinDCX", "KuCoin"))
    rec = RecordingTransport()
    with tempfile.TemporaryDirectory() as d, LabelStore() as store:
        fetcher = Fetcher(ChainCache(Path(d) / "c.duckdb"), rec, offline=False)
        labels = RecordingLabels(store, cfg.entities)
        result = discover("tron", *crawl_providers(fetcher, cfg), labels, cfg)
    _write("crawl_tron", "discover() on Tron: CoinDCX and KuCoin wallets, window from "
           "2026-09-24, first 5 senders per wallet, live TronGrid", rec,
           labels=dict(sorted(labels.seen.items())),
           expected={"findings": [asdict(f) for f in result.findings],
                     "stats": result.stats, "totals": result.totals})
    for f in result.findings:
        print(f"  {f.entity:<8} {f.address} {f.status:<8} {f.rule:<10} {f.confidence}")


def record_holdout() -> None:
    """A tiny real hold-out run on Ethereum: 6 tagged Bitget deposit addresses and
    6 tagged non-deposit addresses (seed 26182), read through Etherscan."""
    from vaspfusion.chains.evm import EvmProvider
    from vaspfusion.discover.evaluate import EvalConfig, evaluate, sample
    from vaspfusion.labels.lookup import LabelStore

    cfg = EvalConfig(n_positive=6, n_negative=6, limit=50)
    rec = RecordingTransport()
    with tempfile.TemporaryDirectory() as d, LabelStore() as store:
        fetcher = Fetcher(ChainCache(Path(d) / "c.duckdb"), rec, offline=False)
        groups = sample(store, cfg)
        labels = RecordingLabels(store)
        report = evaluate(EvmProvider("ethereum", fetcher, page_size=cfg.limit, max_pages=1),
                          labels, *groups, cfg)
    _write("holdout_eth", "evaluate() on Ethereum: 6 Etherscan-tagged Bitget deposit addresses "
           "and 6 tagged non-deposit addresses (seed 26182), live Etherscan v2", rec,
           labels=dict(sorted(labels.seen.items())),
           groups={"positives": groups[0], "neg_exchange": groups[1], "neg_other": groups[2]},
           expected={"metrics": report.metrics, "rows": report.rows})
    for r in report.rows:
        print(f"  {r['truth']:<16}{r['address']} {r['outcome']:<14}{r['entity']} {r['reason']}")


if __name__ == "__main__":
    wanted = sys.argv[1:] or ["gas"]
    for name in wanted:
        {"gas": record_gas, "crawl": record_crawl, "holdout": record_holdout}[name]()
