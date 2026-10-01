"""`asset=` asks an adapter for one asset only, so a trace that follows USDT does not
page through (or get its `limit` used up by) every other asset the wallet moved."""
from decimal import Decimal

import pytest

from vaspfusion.chains import get_provider
from vaspfusion.chains.evm import EvmProvider
from vaspfusion.chains.tron import TronProvider

TRON = "TGjpmhAFT6d7eBKvaFwPVN6H2pDKgLLZiw"          # CoinDCX 1
ETH_DEP = "0x0008ea70c0ef744f4d8ebe412b9bd875b40c8f24"  # "Bitget Dep:" with real + fake USDT
ETH_DEP2 = "0x000483c56fe99127fbd62da5d8b899a159116dc1"  # "Bitget Dep:", ETH only


def test_tron_usdt_only_skips_the_raw_listing(fixture_fetcher):
    f = fixture_fetcher("tron_usdt")
    rows = TronProvider(f, page_size=3, key="").transfers(TRON, "both", limit=7, asset="USDT")
    assert rows and {r.asset for r in rows} == {"USDT"}
    assert f.transport.calls == 3          # the 3 TRC-20 pages; no /transactions pages


def test_tron_native_only_skips_trc20(fixture_fetcher):
    f = fixture_fetcher("tron_usdt")
    rows = TronProvider(f, page_size=3, key="").transfers(TRON, "both", limit=7, asset="TRX")
    assert rows and {r.asset for r in rows} == {"TRX"}
    assert f.transport.calls == 4          # only the raw /transactions pages


def test_evm_stablecoin_only_filters_by_contract(fixture_fetcher):
    f = fixture_fetcher("eth_asset_usdt")
    p = EvmProvider("ethereum", f, page_size=3, max_pages=2, key="test-key")
    rows = p.transfers(ETH_DEP, "both", limit=6, asset="USDT")
    # the fake "USDT" token and the ETH gas top-up are not fetched at all
    assert [(r.asset, r.amount) for r in rows][:2] == [("USDT", Decimal(300000)),
                                                      ("USDT", Decimal(300000))]
    assert {r.asset for r in rows} == {"USDT"}
    assert all("action=tokentx" in page["query"] and "contractaddress=" in page["query"]
               for page in f.trail)
    assert all(r.asset_contract == "0xdac17f958d2ee523a2206206994597c13d831ec7" for r in rows)


def test_evm_native_only_skips_tokentx(fixture_fetcher):
    f = fixture_fetcher("eth_etherscan")
    p = EvmProvider("ethereum", f, page_size=3, max_pages=3, key="test-key")
    rows = p.transfers(ETH_DEP2, "both", limit=5, asset="ETH")
    assert rows and {r.asset for r in rows} == {"ETH"}
    assert f.trail and all("action=txlist" in page["query"] for page in f.trail)


@pytest.mark.parametrize("make", [
    lambda f: TronProvider(f, key=""),
    lambda f: EvmProvider("ethereum", f, key="test-key"),
])
def test_an_asset_the_adapter_cannot_trace_is_an_error(fixture_fetcher, make):
    with pytest.raises(ValueError, match="DOGE"):
        make(fixture_fetcher("tron_usdt")).transfers(
            TRON if make(fixture_fetcher("tron_usdt")).chain == "tron" else ETH_DEP,
            asset="DOGE")


def test_traceable_assets_put_stablecoins_before_the_native_coin(fixture_fetcher):
    f = fixture_fetcher("tron_usdt")
    assert TronProvider(f, key="").traceable_assets == ("USDT", "TRX")
    assert EvmProvider("ethereum", f, key="k").traceable_assets == ("USDT", "USDC", "ETH")
    assert EvmProvider("base", f, key="").traceable_assets == ("USDC", "ETH")
    assert get_provider("bitcoin", f).traceable_assets == ("BTC",)


def test_get_provider_passes_paging_options(fixture_fetcher):
    f = fixture_fetcher("tron_usdt")
    p = get_provider("tron", f, page_size=50, max_pages=2)
    assert (p.page_size, p.max_pages) == (50, 2)
    e = get_provider("ethereum", f, page_size=100, max_pages=1, key="k")
    assert (e.page_size, e.max_pages, e.kind) == (100, 1, "etherscan")
    assert get_provider("bitcoin", f, page_size=50, max_pages=3).max_pages == 3
