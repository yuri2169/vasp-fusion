"""Record the chain-adapter test fixtures from the live APIs (run once, commit the JSON).

    python scripts/record_chain_fixtures.py            # all scenarios
    python scripts/record_chain_fixtures.py tron_usdt  # one

Each scenario drives the real provider with a RecordingTransport, so the fixture
holds exactly the requests the provider makes, keyed by request_key() (API keys
stripped) with the untouched response body. Tests replay them through
FixtureTransport (tests/chains/conftest.py) and never reach the network.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vaspfusion.chains.base import ProviderError  # noqa: E402
from vaspfusion.chains.cache import ChainCache, Fetcher, request_key  # noqa: E402
from vaspfusion.chains.http import UrllibTransport  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "chains"


class RecordingTransport(UrllibTransport):
    def __init__(self):
        super().__init__()
        self.responses: dict[str, dict] = {}

    def get(self, url, params, headers):
        status, body = super().get(url, params, headers)
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = body.decode(errors="replace")
        self.responses[request_key(url, params)] = {"status": status, "body": parsed}
        return status, body


def _run(name: str, source: str, fn) -> None:
    rec = RecordingTransport()
    with tempfile.TemporaryDirectory() as d:
        fetcher = Fetcher(ChainCache(Path(d) / "c.duckdb"), rec, offline=False)
        try:
            rows = fn(fetcher)
            note = f"{len(rows)} transfers"
        except ProviderError as e:
            note = f"raised {type(e).__name__}: {e}"
    OUT.mkdir(parents=True, exist_ok=True)
    doc = {"_source": source, "_recorded": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
           "_result": note, "responses": rec.responses}
    text = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    for secret in _secrets():
        assert secret not in text, f"an API key leaked into fixture {name}"
    (OUT / f"{name}.json").write_text(text)
    print(f"{name}: {len(rec.responses)} responses, {note}")


def _secrets() -> list[str]:
    from vaspfusion.chains.http import api_key
    return [k for k in (api_key("TRONGRID_API_KEY"), api_key("ETHERSCAN_API_KEY")) if k]


# ------------------------------------------------------------------ scenarios
TRON_ADDR = "TGjpmhAFT6d7eBKvaFwPVN6H2pDKgLLZiw"


def tron_usdt(f):
    from vaspfusion.chains.tron import TronProvider
    p = TronProvider(f, page_size=3)
    return p.transfers(TRON_ADDR, "both", limit=7)


def tron_since_in(f):
    from vaspfusion.chains.tron import TronProvider
    p = TronProvider(f, page_size=3)
    return p.transfers(TRON_ADDR, "in", since=datetime(2022, 7, 1, tzinfo=timezone.utc), limit=4)


SCENARIOS = {
    "tron_usdt": (f"TronGrid, {TRON_ADDR} (CoinDCX 1, Dune spellbook), page_size=3", tron_usdt),
    "tron_since_in": (f"TronGrid, {TRON_ADDR}, direction=in since 2022-07-01", tron_since_in),
}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(SCENARIOS)
    for name in wanted:
        source, fn = SCENARIOS[name]
        _run(name, source, fn)
