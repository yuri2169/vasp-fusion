"""BTC (basic) on the recorded mempool.space history of a Poloniex address, plus the
Solana stub and the provider registry."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from chainfix import load_fixture
from vaspfusion.chains import get_provider
from vaspfusion.chains.base import CacheMiss, InvalidAddress, UnsupportedChain
from vaspfusion.chains.btc import BtcProvider

ADDR = "1NBX1UZE3EFPTnYNkDfVhRADvVc8v6pRYu"   # Poloniex (label CSV), 72 txs


def raw_txs():
    return [t for v in load_fixture("btc_pages")["responses"].values() for t in v["body"]]


def inputs(tx):
    return [(v.get("prevout") or {}).get("scriptpubkey_address") for v in tx["vin"]]


def all_rows(fixture_fetcher, **kw):
    return BtcProvider(fixture_fetcher("btc_pages"), max_pages=3).transfers(ADDR, "both", **kw)


def test_follows_both_pages_to_the_end(fixture_fetcher):
    f = fixture_fetcher("btc_pages")
    BtcProvider(f, max_pages=3).transfers(ADDR, "both", limit=500)
    assert f.transport.calls == 2
    assert len({t["txid"] for t in raw_txs()}) == 72


def test_amounts_match_raw_outputs(fixture_fetcher):
    rows = all_rows(fixture_fetcher, limit=500)
    txs = raw_txs()
    sats_in = sum(o["value"] for t in txs if ADDR not in inputs(t)
                  for o in t["vout"] if o.get("scriptpubkey_address") == ADDR)
    sats_out = sum(o["value"] for t in txs if ADDR in inputs(t)
                   for o in t["vout"] if o.get("scriptpubkey_address") not in (ADDR, None))
    assert sum(r.amount for r in rows if r.to_addr == ADDR) == Decimal(sats_in).scaleb(-8)
    assert sum(r.amount for r in rows if r.from_addr == ADDR) == Decimal(sats_out).scaleb(-8)
    assert len(rows) == 73
    assert [r.block_time for r in rows] == sorted(r.block_time for r in rows)


def test_outbound_rows_skip_change(fixture_fetcher):
    rows = all_rows(fixture_fetcher, limit=500)
    assert not [r for r in rows if r.from_addr == ADDR and r.to_addr == ADDR]
    t = next(r for r in rows
             if r.tx_hash == "952ef952a0abf0c4fb49faf8079a84ac0d952c9dbd5c8d44e20419b4914d6b1d")
    assert (t.from_addr, t.to_addr, t.amount) == (ADDR, "33Mz8zrWx6yei6itk2mjfCytdKJZEwKeM6",
                                                  Decimal(35))
    assert t.block_time == datetime(2024, 12, 26, 14, 42, 50, tzinfo=timezone.utc)
    oldest = min(tx["status"]["block_time"] for tx in raw_txs())
    assert rows[0].block_time.timestamp() == oldest


def test_limit_without_since_keeps_most_recent(fixture_fetcher):
    everything = all_rows(fixture_fetcher, limit=500)
    recent = all_rows(fixture_fetcher, limit=5)
    assert recent == everything[-5:]


def test_since_and_direction(fixture_fetcher):
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    p = BtcProvider(fixture_fetcher("btc_pages"), max_pages=3)
    out = p.transfers(ADDR, "out", since=since, limit=500)
    assert out and all(r.from_addr == ADDR and r.block_time >= since for r in out)
    # this address received nothing in 2026 (checked against the raw pages)
    assert p.transfers(ADDR, "in", since=since, limit=500) == []
    inbound = p.transfers(ADDR, "in", limit=500)
    assert inbound and all(r.to_addr == ADDR and r.from_addr != ADDR for r in inbound)


def test_offline_replay_identical(fixture_fetcher):
    live = all_rows(fixture_fetcher, limit=500)
    f2 = fixture_fetcher("btc_pages", offline=True)
    assert BtcProvider(f2, max_pages=3).transfers(ADDR, "both", limit=500) == live
    assert f2.transport.calls == 0


def test_offline_other_address_misses(fixture_fetcher):
    with pytest.raises(CacheMiss):
        BtcProvider(fixture_fetcher("btc_pages", offline=True)).transfers(
            "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h")


def test_invalid_address(fixture_fetcher):
    with pytest.raises(InvalidAddress):
        BtcProvider(fixture_fetcher("btc_pages")).transfers("TGjpmhAFT6d7eBKvaFwPVN6H2pDKgLLZiw")


def test_solana_stub(fixture_fetcher):
    p = get_provider("solana", fixture_fetcher("btc_pages"))
    with pytest.raises(UnsupportedChain, match="Solana"):
        p.transfers("So11111111111111111111111111111111111111112")
    with pytest.raises(InvalidAddress):
        p.transfers("not-an-address")


@pytest.mark.parametrize("chain,cls", [
    ("tron", "TronProvider"), ("ethereum", "EvmProvider"), ("polygon", "EvmProvider"),
    ("arbitrum", "EvmProvider"), ("base", "EvmProvider"), ("optimism", "EvmProvider"),
    ("bitcoin", "BtcProvider"), ("solana", "SolanaProvider"),
])
def test_registry(fixture_fetcher, chain, cls):
    assert type(get_provider(chain, fixture_fetcher("btc_pages"))).__name__ == cls


@pytest.mark.parametrize("chain", ["bsc", "avalanche", "dogecoin"])
def test_registry_unsupported_without_paid_key(fixture_fetcher, chain):
    with pytest.raises(UnsupportedChain):
        get_provider(chain, fixture_fetcher("btc_pages"))


def test_every_trace_chain_is_known():
    from typing import get_args

    from vaspfusion.api.schemas import TraceChain
    from vaspfusion.chains.addresses import EVM_FAMILY
    assert set(get_args(TraceChain)) <= set(EVM_FAMILY) | {"tron", "bitcoin", "solana"}
