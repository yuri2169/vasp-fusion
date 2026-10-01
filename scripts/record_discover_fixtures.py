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


if __name__ == "__main__":
    wanted = sys.argv[1:] or ["gas"]
    for name in wanted:
        {"gas": record_gas}[name]()
