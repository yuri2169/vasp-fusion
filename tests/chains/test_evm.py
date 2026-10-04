"""EVM adapter on recorded Etherscan v2 / Blockscout responses (real Bitget deposit
addresses and a Gate.io proof-of-reserves wallet on Base)."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from chainfix import load_fixture
from vaspfusion.chains.base import CacheMiss, InvalidAddress, ProviderError, Retryable, \
    UnsupportedChain
from vaspfusion.chains.evm import EvmProvider, _check

DEP = "0x0008ea70c0ef744f4d8ebe412b9bd875b40c8f24"      # "Bitget Dep:" with real + fake USDT
DEP2 = "0x000483c56fe99127fbd62da5d8b899a159116dc1"     # "Bitget Dep:", ETH only
HOT = "0x1ab4973a48dc892cd9971ece8e01dcc7688f8f23"      # where both deposits were swept
GATE_BASE = "0x0d0707963952f2fba59dd06f2b425ace40b492fe"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
FAKE_USDT = "0x88842fd5fa3ad21555b98ceb407593aa69af7388"


def eth(fetcher, key="test-key"):
    # any non-empty key selects the Etherscan backend; apikey is not part of the fixture key
    return EvmProvider("ethereum", fetcher, page_size=3, max_pages=2, key=key)


def test_usdt_deposit_and_sweep(fixture_fetcher):
    rows = eth(fixture_fetcher("eth_usdt")).transfers(DEP, "both", limit=6)
    assert len(rows) == 6
    usdt = [r for r in rows if r.asset == "USDT"]
    assert [(r.to_addr, r.amount) for r in usdt] == [(DEP, Decimal(300000)), (HOT, Decimal(300000))]
    assert all(r.amount_usd == r.amount and r.asset_contract == USDT for r in usdt)
    # the hot wallet paid this deposit address's gas before the sweep
    gas = next(r for r in rows if r.asset == "ETH" and r.from_addr == HOT)
    assert gas.to_addr == DEP and gas.amount == Decimal("0.002427667456")


def test_fake_usdt_is_not_called_usdt(fixture_fetcher):
    rows = eth(fixture_fetcher("eth_usdt")).transfers(DEP, "both", limit=6)
    fake = [r for r in rows if r.asset_contract == FAKE_USDT]
    assert len(fake) == 1
    assert fake[0].asset == f"USDT@{FAKE_USDT}" and fake[0].amount_usd is None
    raw = next(x for page in load_fixture("eth_usdt")["responses"].values()
               if isinstance(page["body"]["result"], list)
               for x in page["body"]["result"] if x.get("contractAddress") == FAKE_USDT)
    assert raw["tokenSymbol"] == "USDT"  # it claims to be USDT on-chain


def test_native_amount_exact_18_decimals(fixture_fetcher):
    rows = eth(fixture_fetcher("eth_etherscan")).transfers(DEP2, "both", limit=5)
    assert len(rows) == 4
    first = rows[0]
    raw = next(x for page in load_fixture("eth_etherscan")["responses"].values()
               if isinstance(page["body"]["result"], list)
               for x in page["body"]["result"] if x["hash"] == first.tx_hash)
    assert first.amount == Decimal(raw["value"]) / Decimal(10) ** 18
    assert first.amount == Decimal("0.036282674618469786")
    assert first.fee_payer == first.from_addr
    assert first.block_time == datetime(2024, 2, 21, 6, 58, 35, tzinfo=timezone.utc)


def test_since_uses_start_block_and_direction_out(fixture_fetcher):
    f = fixture_fetcher("eth_since_out")
    since = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = eth(f).transfers(DEP2, "out", since=since, limit=3)
    assert [r.to_addr for r in rows] == [HOT, HOT]
    assert all(r.from_addr == DEP2 and r.block_time >= since for r in rows)
    queries = [e["query"] for e in f.trail]
    assert any("getblocknobytime" in q and "timestamp=1704067200" in q for q in queries)
    assert all("startblock=18908895" in q for q in queries if "action=txlist" in q)


def test_mixed_case_input_is_normalised(fixture_fetcher):
    from vaspfusion.chains.addresses import eip55
    rows = eth(fixture_fetcher("eth_etherscan")).transfers(eip55(DEP2), "both", limit=5)
    assert len(rows) == 4


def test_blockscout_backend_keyless(fixture_fetcher):
    f = fixture_fetcher("base_blockscout")
    p = EvmProvider("base", f, page_size=3, max_pages=2, key="")
    assert p.kind == "blockscout"
    rows = p.transfers(GATE_BASE, "both", limit=4)
    assert len(rows) == 4
    assert all(GATE_BASE in (r.from_addr, r.to_addr) for r in rows)
    assert all("apikey" not in e["query"] for e in f.trail)
    toshi = next(r for r in rows if r.asset.startswith("TOSHI@"))
    assert toshi.amount == Decimal(92549652)


def test_ethereum_without_key_falls_back_to_blockscout(fixture_fetcher):
    p = EvmProvider("ethereum", fixture_fetcher("eth_etherscan"), key="")
    assert (p.kind, p.target) == ("blockscout", "https://eth.blockscout.com/api")


def test_etherscan_free_plan_refusal_is_unsupported_chain():
    # the body Etherscan v2 gave for chainid=56 on a free key (measured 1 Oct 2026)
    with pytest.raises(UnsupportedChain, match="Free API access"):
        _check({"status": "0", "message": "NOTOK", "result": "Free API access is not supported "
                "for this chain. Please upgrade your api plan for full chain coverage."})


def test_offline_replay_identical(fixture_fetcher):
    live = eth(fixture_fetcher("eth_usdt")).transfers(DEP, "both", limit=6)
    f2 = fixture_fetcher("eth_usdt", offline=True)
    assert eth(f2).transfers(DEP, "both", limit=6) == live
    assert f2.transport.calls == 0
    with pytest.raises(CacheMiss):
        eth(f2).transfers(DEP, "in", limit=6)


def test_invalid_address(fixture_fetcher):
    with pytest.raises(InvalidAddress):
        eth(fixture_fetcher("eth_usdt")).transfers("TGjpmhAFT6d7eBKvaFwPVN6H2pDKgLLZiw")


def test_check_classifies_bodies():
    _check({"status": "1", "message": "OK", "result": []})
    _check({"status": "0", "message": "No transactions found", "result": []})
    with pytest.raises(Retryable):
        _check({"status": "0", "message": "NOTOK",
                "result": "Max calls per sec rate limit reached (3/sec)"})
    with pytest.raises(ProviderError, match="Invalid API Key"):
        _check({"status": "0", "message": "NOTOK", "result": "Invalid API Key"})
