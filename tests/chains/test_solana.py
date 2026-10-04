"""Solana through Helius' parsed history, on recorded responses (an HTX reserve wallet
from the label store). Recorded with a free key on 4 Oct 2026 (UTC)."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from chainfix import load_fixture
from vaspfusion.chains import get_provider
from vaspfusion.chains.base import CacheMiss, InvalidAddress, ProviderError, Retryable, \
    UnsupportedChain
from vaspfusion.chains.solana import STABLECOINS, SolanaProvider, _check

HTX = "5bJcc9eb2XE7mqcET2xDuAdMGuXWybb4YPmAHLjKLhQG"       # HTX reserve (DefiLlama)
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SINCE = datetime(2026, 10, 3, tzinfo=timezone.utc)
SENDER = "2RKV9XmHc5YYrZFDvN7UjysXVzzesrXqHdwY68Jy7XwG"


def first(fetcher):
    return SolanaProvider(fetcher, page_size=5, max_pages=2)


def raw_txs(name):
    return sorted((tx for page in load_fixture(name)["responses"].values() for tx in page["body"]),
                  key=lambda tx: tx["timestamp"])


def test_the_sender_constant_is_the_recorded_one():
    assert SENDER in {tx["feePayer"] for tx in raw_txs("solana_helius")}


def test_sol_and_token_transfers_oldest_first(fixture_fetcher):
    rows = first(fixture_fetcher("solana_helius")).transfers(HTX, "both", limit=8)
    assert [(r.asset.split("@")[0], r.amount) for r in rows] == [
        ("SOL", Decimal("0.092")), ("SOL", Decimal("0.089547864")), ("?", Decimal("8.84")),
        ("?", Decimal("2")), ("?", Decimal("2")), ("USDT", Decimal("1.5")),
        ("USDC", Decimal("0.88")), ("?", Decimal("3.456"))]
    assert rows == sorted(rows, key=lambda r: r.block_time)
    assert rows[0].block_time == datetime(2023, 12, 7, 7, 33, 8, tzinfo=timezone.utc)
    assert rows[0].tx_hash.startswith("5WTghYNfM8") and rows[0].asset_contract is None
    assert rows.complete is False                           # two pages of a long history


def test_a_token_transfer_names_the_owning_wallets_not_the_token_accounts(fixture_fetcher):
    rows = first(fixture_fetcher("solana_helius")).transfers(HTX, "both", limit=8)
    usdt = next(r for r in rows if r.asset == "USDT")
    raw = next(t for tx in raw_txs("solana_helius") for t in tx["tokenTransfers"]
               if tx["signature"] == usdt.tx_hash)
    assert raw["mint"] == USDT_MINT
    assert (usdt.from_addr, usdt.to_addr) == (raw["fromUserAccount"], raw["toUserAccount"]) \
        == (SENDER, HTX)
    token_accounts = {raw["fromTokenAccount"], raw["toTokenAccount"]}
    assert len(token_accounts) == 2 and not token_accounts & {usdt.from_addr, usdt.to_addr}
    assert usdt.asset_contract == USDT_MINT and usdt.amount_usd == usdt.amount == Decimal("1.5")
    usdc = next(r for r in rows if r.asset == "USDC")
    assert usdc.asset_contract == USDC_MINT and usdc.amount_usd == Decimal("0.88")
    assert STABLECOINS[USDT_MINT] == ("USDT", 6) and STABLECOINS[USDC_MINT] == ("USDC", 6)


def test_the_fee_payer_is_the_first_signer(fixture_fetcher):
    rows = first(fixture_fetcher("solana_helius")).transfers(HTX, "both", limit=8)
    payers = {tx["signature"]: tx["feePayer"] for tx in raw_txs("solana_helius")}
    assert all(r.fee_payer == payers[r.tx_hash] for r in rows)
    assert rows[1].from_addr == HTX and rows[1].fee_payer == HTX     # its own outgoing SOL


def test_a_token_with_no_known_mint_is_named_by_its_mint(fixture_fetcher):
    rows = first(fixture_fetcher("solana_helius")).transfers(HTX, "both", limit=8)
    other = rows[2]
    assert other.asset == f"?@{other.asset_contract}" and other.amount_usd is None


def test_rent_paid_into_a_new_token_account_is_not_a_transfer():
    """Seen from the sender: it paid 0.00203928 SOL into the token account the same
    transaction opened for the receiver. That is the account's rent, not a payment."""
    tx = next(tx for tx in raw_txs("solana_helius")
              if tx["feePayer"] == SENDER and tx["tokenTransfers"]
              and tx["tokenTransfers"][0]["mint"] == USDT_MINT)
    rent = [n for n in tx["nativeTransfers"] if n["fromUserAccount"] == SENDER]
    assert [(n["toUserAccount"], n["amount"]) for n in rent] == [
        (tx["tokenTransfers"][0]["toTokenAccount"], 2039280)]
    got = SolanaProvider.__new__(SolanaProvider)._parse(tx, SENDER)
    assert [(t.asset, t.to_addr, t.amount) for t in got] == [("USDT", HTX, Decimal("1.5"))]


def test_a_failed_transaction_is_dropped():
    tx = dict(raw_txs("solana_helius")[0])
    p = SolanaProvider.__new__(SolanaProvider)
    assert len(p._parse(tx, HTX)) == 1
    # the field Helius sets on a transaction that did not execute
    tx["transactionError"] = {"InstructionError": [0, {"Custom": 1}]}
    assert p._parse(tx, HTX) == []


def test_since_reads_to_the_end_of_the_listing(fixture_fetcher):
    p = SolanaProvider(fixture_fetcher("solana_usdt"), page_size=20, max_pages=3)
    rows = p.transfers(HTX, "both", since=SINCE, limit=50)
    assert len(rows) == 12 and rows.complete is True
    assert all(r.block_time >= SINCE for r in rows)
    assert [r.amount for r in rows if r.asset == "USDT"] == [Decimal("0.0001")] * 2


def test_asset_and_direction_filters_share_one_cached_listing(fixture_fetcher):
    f = fixture_fetcher("solana_usdt")
    p = SolanaProvider(f, page_size=20, max_pages=3)
    usdt = p.transfers(HTX, "both", since=SINCE, limit=50, asset="USDT")
    assert len(usdt) == 2 and {r.asset for r in usdt} == {"USDT"}
    assert f.stats == {"hits": 0, "live": 1, "retries": 0}
    out = p.transfers(HTX, "out", since=SINCE, limit=50, asset="SOL")
    assert [(r.from_addr, r.amount) for r in out] == [(HTX, Decimal("1600"))]
    inbound = p.transfers(HTX, "in", since=SINCE, limit=50)
    assert len(inbound) == 11 and all(r.to_addr == HTX for r in inbound)
    assert f.stats == {"hits": 2, "live": 1, "retries": 0}
    with pytest.raises(ValueError, match="traceable"):
        p.transfers(HTX, "both", asset="BONK")


def test_limit_cuts_the_rows_and_says_so(fixture_fetcher):
    p = SolanaProvider(fixture_fetcher("solana_usdt"), page_size=20, max_pages=3)
    rows = p.transfers(HTX, "both", since=SINCE, limit=3)
    assert len(rows) == 3 and rows.complete is False


def test_offline_replay_is_identical_and_holds_no_key(fixture_fetcher, monkeypatch):
    monkeypatch.setenv("HELIUS_API_KEY", "SECRET-HELIUS-KEY")
    f = fixture_fetcher("solana_helius")
    live = first(f).transfers(HTX, "both", limit=8)
    assert f.stats["live"] == 2
    assert all("SECRET" not in page["query"] and "api-key" not in page["query"]
               for page in f.trail)
    off = fixture_fetcher(offline=True)                     # same cache file, no transport
    assert first(off).transfers(HTX, "both", limit=8) == live
    with pytest.raises(CacheMiss):
        first(off).transfers(HTX, "both", limit=8, since=SINCE)


def test_without_a_key_solana_is_refused(fixture_fetcher):
    """Helius' own answer to a request with no key, as recorded."""
    p = SolanaProvider(fixture_fetcher("solana_no_key"), page_size=5)
    with pytest.raises(UnsupportedChain, match="HELIUS_API_KEY"):
        p.transfers(HTX, "both", limit=3)


def test_invalid_address_and_errors(fixture_fetcher):
    with pytest.raises(InvalidAddress):
        first(fixture_fetcher("solana_helius")).transfers("0x8894e0a0c962cb723c1976a4421c95949be2d4e3")
    _check([])
    with pytest.raises(ProviderError, match="invalid address"):     # as Helius worded it
        _check({"error": "invalid address"})
    with pytest.raises(Retryable):
        _check({"error": "rate limit exceeded"})


def test_the_registry_passes_the_trace_paging_options(fixture_fetcher):
    p = get_provider("solana", fixture_fetcher("solana_helius"), page_size=5, max_pages=2,
                     key="ignored")
    assert (p.page_size, p.max_pages) == (5, 2)
    assert get_provider("solana", fixture_fetcher("solana_helius"), page_size=500).page_size == 100
    assert p.traceable_assets == ("USDT", "USDC", "SOL")
