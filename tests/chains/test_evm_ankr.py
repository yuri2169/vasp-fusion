"""BNB Chain through Ankr's Advanced API, on recorded responses (a Binance hot wallet
from the label store). Recorded with a free key on 4 Oct 2026 (UTC)."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from chainfix import load_fixture
from vaspfusion.chains.base import CacheMiss, ProviderError, Retryable, UnsupportedChain
from vaspfusion.chains.evm import ANKR, EvmProvider, _check_ankr

HOT = "0x8894e0a0c962cb723c1976a4421c95949be2d4e3"      # Binance hot wallet (eth-labels)
USDT = "0x55d398326f99059ff775485246999027b3197955"
USDC = "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"
SINCE = datetime(2026, 10, 1, tzinfo=timezone.utc)


def bsc(fetcher, **kw):
    return EvmProvider("bsc", fetcher, **kw)


def test_bsc_is_read_from_ankr_whatever_the_etherscan_key(fixture_fetcher):
    for key in ("", "a-free-key"):
        p = bsc(fixture_fetcher("bsc_ankr"), key=key)
        assert (p.kind, p.target) == ("ankr", "bsc")


def test_a_paid_etherscan_plan_is_the_first_choice(fixture_fetcher, monkeypatch):
    monkeypatch.setenv("ETHERSCAN_PAID", "1")
    p = bsc(fixture_fetcher("bsc_ankr"), key="a-paid-key")
    assert (p.kind, p.target) == ("etherscan", 56)
    assert bsc(fixture_fetcher("bsc_ankr"), key="").kind == "ankr"     # the flag alone is no key


def test_native_and_token_transfers_oldest_first(fixture_fetcher):
    rows = bsc(fixture_fetcher("bsc_ankr"), page_size=3, max_pages=2).transfers(HOT, "both", limit=5)
    assert [(r.asset.split("@")[0], r.amount) for r in rows] == [
        ("AVAX", Decimal("199.989")), ("BNB", Decimal("0.9995")), ("AVAX", Decimal("0.089")),
        ("BNB", Decimal("10000")), ("BAL", Decimal("1052337"))]
    assert rows == sorted(rows, key=lambda r: r.block_time)
    assert rows[0].block_time == datetime(2021, 6, 7, 9, 12, 58, tzinfo=timezone.utc)
    assert rows.complete is False                       # the wallet has far more than two pages
    assert all(r.chain == "bsc" and r.from_addr == r.from_addr.lower() for r in rows)


def test_the_sender_of_a_native_transfer_paid_its_gas(fixture_fetcher):
    rows = bsc(fixture_fetcher("bsc_ankr"), page_size=3, max_pages=2).transfers(HOT, "both", limit=5)
    bnb = [r for r in rows if r.asset == "BNB"]
    assert [(r.from_addr, r.fee_payer, r.asset_contract) for r in bnb] == [
        ("0xb1256d6b31e4ae87da1d56e5890c66be7f1c038e",
         "0xb1256d6b31e4ae87da1d56e5890c66be7f1c038e", None),
        ("0xf977814e90da44bfa03b6295a0616a897441acec",
         "0xf977814e90da44bfa03b6295a0616a897441acec", None)]
    # a token transfer's gas payer is not in the listing
    assert all(r.fee_payer is None for r in rows if r.asset != "BNB")


def test_a_token_outside_the_stablecoin_table_is_named_by_its_contract(fixture_fetcher):
    rows = bsc(fixture_fetcher("bsc_ankr"), page_size=3, max_pages=2).transfers(HOT, "both", limit=5)
    assert rows[0].asset == "AVAX@0x1ce0c2827e2ef14d5c4f29a091d735a204794041"
    assert rows[0].amount_usd is None


def test_usdt_on_bnb_chain_has_18_decimals(fixture_fetcher):
    """The provider's own token metadata says 18; a 6-decimal reading would make
    28.65 USDT into 28 trillion."""
    raw = load_fixture("bsc_ankr_usdt")["responses"]
    meta = {(t["contractAddress"].lower(), t["tokenDecimals"]) for page in raw.values()
            for t in page["body"]["result"]["transfers"]
            if t["contractAddress"].lower() in (USDT, USDC)}
    assert meta == {(USDT, 18), (USDC, 18)}
    p = bsc(fixture_fetcher("bsc_ankr_usdt"), page_size=5, max_pages=3)
    rows = p.transfers(HOT, "both", since=SINCE, limit=4, asset="USDT")
    assert [(r.asset, r.amount, r.amount_usd, r.asset_contract) for r in rows] == [
        ("USDT", Decimal("28.65000482"), Decimal("28.65000482"), USDT),
        ("USDT", Decimal("149.99"), Decimal("149.99"), USDT)]


def test_an_asset_filter_reads_only_the_token_listing(fixture_fetcher):
    f = fixture_fetcher("bsc_ankr_usdt")
    bsc(f, page_size=5, max_pages=3).transfers(HOT, "both", since=SINCE, limit=4, asset="USDT")
    assert f.stats["live"] == 3
    assert all("ankr_getTokenTransfers" in page["query"] for page in f.trail)


def test_since_and_direction(fixture_fetcher):
    p = bsc(fixture_fetcher("bsc_ankr_since_out"), page_size=5, max_pages=2)
    rows = p.transfers(HOT, "out", since=SINCE, limit=4)
    assert len(rows) == 3
    assert all(r.from_addr == HOT and r.block_time >= SINCE for r in rows)
    assert {r.asset for r in rows} == {"USDT", "USDC"}
    # the same recorded pages, read for the other direction: nothing is fetched again
    f = fixture_fetcher("bsc_ankr_since_out")
    both = bsc(f, page_size=5, max_pages=2).transfers(HOT, "both", since=SINCE, limit=50)
    live = f.stats["live"]
    inbound = bsc(f, page_size=5, max_pages=2).transfers(HOT, "in", since=SINCE, limit=50)
    assert f.stats["live"] == live
    assert all(r.to_addr == HOT for r in inbound)
    assert len(inbound) + len(rows) == len(both)


def test_offline_replay_is_identical_and_holds_no_key(fixture_fetcher, monkeypatch):
    monkeypatch.setenv("ANKR_API_KEY", "SECRET-ANKR-KEY")
    f = fixture_fetcher("bsc_ankr")
    live = bsc(f, page_size=3, max_pages=2).transfers(HOT, "both", limit=5)
    assert all("SECRET-ANKR-KEY" not in page["query"] and page["query"].startswith(ANKR + "?")
               for page in f.trail)
    off = fixture_fetcher(offline=True)                 # same cache file, no transport
    assert bsc(off, page_size=3, max_pages=2).transfers(HOT, "both", limit=5) == live
    with pytest.raises(CacheMiss):
        bsc(off, page_size=3, max_pages=2).transfers(HOT, "both", limit=5, since=SINCE)


def test_without_a_key_bnb_chain_is_refused(fixture_fetcher):
    """Ankr's own answer to a request with no key, as recorded."""
    p = bsc(fixture_fetcher("bsc_unsupported"), page_size=3)
    with pytest.raises(UnsupportedChain, match="ANKR_API_KEY"):
        p.transfers(HOT, "both", limit=3)


def test_ankr_errors():
    _check_ankr({"result": {"transfers": []}})
    with pytest.raises(Retryable):                      # the body Ankr sent with HTTP 429
        _check_ankr({"id": None, "jsonrpc": "2.0", "error": {
            "code": -32090, "message": "Too many requests, reason: call rate limit exhausted, "
                                       "retry in 10s"}})
    with pytest.raises(ProviderError, match="invalid blockchain name"):
        _check_ankr({"id": 1, "jsonrpc": "2.0", "error": {
            "code": -32602, "message": "invalid argument 0: invalid params: invalid blockchain "
                                       "name: invalid params: nochain is not allowed."}})
    with pytest.raises(ProviderError):
        _check_ankr([])
