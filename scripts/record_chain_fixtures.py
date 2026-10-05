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
        return self._keep(url, params, *super().get(url, params, headers))

    def rpc(self, url, params, headers, secret=None):
        return self._keep(url, params, *super().rpc(url, params, headers, secret))

    def _keep(self, url, params, status, body):
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
            note = f"{len(rows)} {'answers' if name.startswith('across') else 'transfers'}"
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
    return [k for k in map(api_key, ("TRONGRID_API_KEY", "ETHERSCAN_API_KEY", "HELIUS_API_KEY",
                                     "ANKR_API_KEY")) if k]


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


ETH_ADDR = "0x000483c56fe99127fbd62da5d8b899a159116dc1"   # "Bitget Dep:" (Etherscan tag)
BASE_ADDR = "0x0d0707963952f2fba59dd06f2b425ace40b492fe"  # Gate.io proof-of-reserves
BSC_ADDR = "0x8894e0a0c962cb723c1976a4421c95949be2d4e3"   # probed while planning


def eth_etherscan(f):
    from vaspfusion.chains.evm import EvmProvider
    return EvmProvider("ethereum", f, page_size=3, max_pages=3).transfers(ETH_ADDR, "both", limit=5)


ETH_USDT_ADDR = "0x0008ea70c0ef744f4d8ebe412b9bd875b40c8f24"  # "Bitget Dep:"; real + fake USDT


def eth_usdt(f):
    from vaspfusion.chains.evm import EvmProvider
    p = EvmProvider("ethereum", f, page_size=3, max_pages=2)
    return p.transfers(ETH_USDT_ADDR, "both", limit=6)


def eth_asset_usdt(f):
    from vaspfusion.chains.evm import EvmProvider
    p = EvmProvider("ethereum", f, page_size=3, max_pages=2)
    return p.transfers(ETH_USDT_ADDR, "both", limit=6, asset="USDT")


def eth_since_out(f):
    from vaspfusion.chains.evm import EvmProvider
    p = EvmProvider("ethereum", f, page_size=3, max_pages=3)
    return p.transfers(ETH_ADDR, "out", since=datetime(2024, 1, 1, tzinfo=timezone.utc), limit=3)


def base_blockscout(f):
    from vaspfusion.chains.evm import EvmProvider
    return EvmProvider("base", f, page_size=3, max_pages=2).transfers(BASE_ADDR, "both", limit=4)


def bsc_unsupported(f):
    """What Ankr answers with no key at all: the refusal the adapter turns into
    UnsupportedChain."""
    from vaspfusion.chains.evm import EvmProvider
    p = EvmProvider("bsc", f, page_size=3)
    p.ankr_key = None
    return p.transfers(BSC_ADDR, "both", limit=3)


def bsc_ankr(f):
    from vaspfusion.chains.evm import EvmProvider
    return EvmProvider("bsc", f, page_size=3, max_pages=2).transfers(BSC_ADDR, "both", limit=5)


BSC_SINCE = datetime(2026, 10, 1, tzinfo=timezone.utc)


def bsc_ankr_usdt(f):
    from vaspfusion.chains.evm import EvmProvider
    p = EvmProvider("bsc", f, page_size=5, max_pages=3)
    return p.transfers(BSC_ADDR, "both", since=BSC_SINCE, limit=4, asset="USDT")


def bsc_ankr_since_out(f):
    from vaspfusion.chains.evm import EvmProvider
    p = EvmProvider("bsc", f, page_size=5, max_pages=2)
    return p.transfers(BSC_ADDR, "out", since=BSC_SINCE, limit=4)


SOL_ADDR = "5bJcc9eb2XE7mqcET2xDuAdMGuXWybb4YPmAHLjKLhQG"   # HTX reserve (DefiLlama)
SOL_SINCE = datetime(2026, 10, 3, tzinfo=timezone.utc)


def solana_helius(f):
    from vaspfusion.chains.solana import SolanaProvider
    return SolanaProvider(f, page_size=5, max_pages=2).transfers(SOL_ADDR, "both", limit=8)


def solana_usdt(f):
    from vaspfusion.chains.solana import SolanaProvider
    p = SolanaProvider(f, page_size=20, max_pages=3)
    return p.transfers(SOL_ADDR, "both", since=SOL_SINCE, limit=50)


def solana_no_key(f):
    """What Helius answers with no key: the refusal the adapter turns into
    UnsupportedChain."""
    from vaspfusion.chains.solana import SolanaProvider
    p = SolanaProvider(f, page_size=5)
    p.key = None
    return p.transfers(SOL_ADDR, "both", limit=3)


BTC_ADDR = "1NBX1UZE3EFPTnYNkDfVhRADvVc8v6pRYu"  # Poloniex (label CSV), 72 txs


def btc_pages(f):
    from vaspfusion.chains.btc import BtcProvider
    return BtcProvider(f, max_pages=3).transfers(BTC_ADDR, "both", limit=500)


# Across deposits of the recorded `eth-bridge` wallet, and a transaction of the same
# wallet that is not an Across deposit (it pays another bridge)
ACROSS_DEPOSIT = "0xa72833c9a0c3f13cf1939a230adb33b01a29c8019629caf014c11b5509d50f3f"
ACROSS_SMALL = "0x60c782f004d2fd08ab7fc97ac2a5fc1be493536a84879371a1f97f9b2c239249"
NOT_ACROSS = "0x23922cd41aadb2ac494e52450a034a8a7726042056eaaceb2bc9169189aca636"


def _deposit(tx_hash: str):
    from decimal import Decimal

    from vaspfusion.chains.base import Transfer
    return Transfer("ethereum", tx_hash, datetime(2026, 6, 1, tzinfo=timezone.utc),
                    "0x210297c6996b3008ed6ef0d4deb74b9515f364b0",
                    "0x5c7bcd6e7de5423a257d81b442095a1a6ced35c5", "USDT", Decimal(1), Decimal(1),
                    None)


def across_filled(f):
    from vaspfusion.chains.bridges import AcrossResolver
    r = AcrossResolver(f)
    return [r.resolve(_deposit(ACROSS_DEPOSIT)), r.resolve(_deposit(ACROSS_SMALL))]


def across_unknown(f):
    from vaspfusion.chains.bridges import AcrossResolver
    return [AcrossResolver(f).resolve(_deposit(NOT_ACROSS))]


SCENARIOS = {
    "across_filled": (f"app.across.to deposit index, origin chain 1, {ACROSS_DEPOSIT} and "
                      f"{ACROSS_SMALL}", across_filled),
    "across_unknown": (f"app.across.to deposit index, origin chain 1, {NOT_ACROSS} (not an "
                       "Across deposit: HTTP 404)", across_unknown),
    "btc_pages": (f"mempool.space, {BTC_ADDR}, full history (50 + 22 txs)", btc_pages),
    "eth_etherscan": (f"Etherscan v2 chainid=1, {ETH_ADDR}, page_size=3", eth_etherscan),
    "eth_usdt": (f"Etherscan v2 chainid=1, {ETH_USDT_ADDR}, page_size=3", eth_usdt),
    "eth_asset_usdt": (f"Etherscan v2 chainid=1, {ETH_USDT_ADDR}, asset=USDT only", eth_asset_usdt),
    "eth_since_out": (f"Etherscan v2 chainid=1, {ETH_ADDR}, out since 2024-01-01", eth_since_out),
    "base_blockscout": (f"base.blockscout.com, {BASE_ADDR}, page_size=3", base_blockscout),
    "bsc_unsupported": (f"Ankr Advanced API with no key, bsc, {BSC_ADDR}", bsc_unsupported),
    "bsc_ankr": (f"Ankr Advanced API (free key), bsc, {BSC_ADDR} (Binance hot wallet, "
                 "eth-labels), page_size=3", bsc_ankr),
    "bsc_ankr_usdt": (f"Ankr Advanced API, bsc, {BSC_ADDR}, asset=USDT since 2026-10-01",
                      bsc_ankr_usdt),
    "bsc_ankr_since_out": (f"Ankr Advanced API, bsc, {BSC_ADDR}, out since 2026-10-01",
                           bsc_ankr_since_out),
    "solana_helius": (f"Helius parsed history (free key), {SOL_ADDR} (HTX reserve, "
                      "DefiLlama), oldest first, page_size=5", solana_helius),
    "solana_usdt": (f"Helius parsed history, {SOL_ADDR}, since 2026-10-03, page_size=20",
                    solana_usdt),
    "solana_no_key": (f"Helius parsed history with no key, {SOL_ADDR}", solana_no_key),
    "tron_usdt": (f"TronGrid, {TRON_ADDR} (CoinDCX 1, Dune spellbook), page_size=3", tron_usdt),
    "tron_since_in": (f"TronGrid, {TRON_ADDR}, direction=in since 2022-07-01", tron_since_in),
}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(SCENARIOS)
    for name in wanted:
        source, fn = SCENARIOS[name]
        _run(name, source, fn)
