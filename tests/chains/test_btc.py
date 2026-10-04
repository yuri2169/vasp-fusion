"""BTC (basic) on the recorded mempool.space history of a Poloniex address, plus the
Solana stub and the provider registry."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from chainfix import load_fixture
from vaspfusion.chains import get_provider
from vaspfusion.chains.base import CacheMiss, InvalidAddress, UnsupportedChain
from vaspfusion.chains.btc import (BtcProvider, UtxoTx, coinjoin_ids, fee_share, out_transfers,
                                   tx_frame)

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
    # 44 spends (each pays one other address) + 28 payments in: one row per transaction,
    # also for the payment that has two outputs to this address
    assert len(rows) == 72
    assert [r.block_time for r in rows] == sorted(r.block_time for r in rows)


def test_every_satoshi_of_a_spend_is_a_transfer_change_or_fee(fixture_fetcher):
    p = BtcProvider(fixture_fetcher("btc_pages"), max_pages=3)
    rows = p.transfers(ADDR, "out", limit=500)
    spends = [t for t in raw_txs() if ADDR in inputs(t)]
    assert len(spends) == 44
    for tx in spends:
        put_in = sum(v["prevout"]["value"] for v in tx["vin"]
                     if v["prevout"]["scriptpubkey_address"] == ADDR)
        change = sum(o["value"] for o in tx["vout"] if o.get("scriptpubkey_address") == ADDR)
        sent = sum(r.amount for r in rows if r.tx_hash == tx["txid"])
        fee = p.fee_share(ADDR, tx["txid"])
        assert fee == Decimal(tx["fee"]).scaleb(-8)          # the only input address pays it all
        assert sent + fee + Decimal(change).scaleb(-8) == Decimal(put_in).scaleb(-8)


def wasabi():
    """The Wasabi 1.x coordinator's sweep of its own fees, then two real CoinJoin rounds."""
    return [UtxoTx.from_esplora(t) for t in load_fixture("btc_wasabi_rounds")["transactions"]]


def test_real_wasabi_rounds_are_recognised_and_the_coordinators_own_sweep_is_not():
    sweep, *rounds = wasabi()
    assert len(sweep.input_addresses) == 1 and len(sweep.inputs) == 244
    assert [(len(t.input_addresses), len(t.outputs)) for t in rounds] == [(81, 161), (70, 136)]
    assert coinjoin_ids([sweep, *rounds]) == {t.txid for t in rounds}


def test_the_shape_rule_as_inherited_misses_real_rounds():
    """Why Bitcoin has its own settings. BTC-FUSION's rule asks for the equal outputs to
    be half of all outputs; it was only ever measured on generated data. A real Wasabi
    round also pays change and a second denomination: 67 equal outputs of 161."""
    from vaspfusion.graph.coinjoin import coinjoin_txids
    frame = tx_frame(wasabi())
    assert coinjoin_txids(frame) == set()
    assert len(coinjoin_txids(frame, min_equal=5, min_share=0.25)) == 2


def test_a_participant_of_a_real_round_sends_into_the_sink():
    _, round_, _ = wasabi()
    who = round_.input_addresses[0]
    t, = out_transfers(round_, who, coinjoin=round_.txid in coinjoin_ids([round_]))
    assert t.to_addr == "coinjoin:" + round_.txid
    assert t.amount + fee_share(round_, who) == Decimal(round_.put_in(who)).scaleb(-8)


def test_the_newest_page_alone_and_whether_it_is_the_whole_history(fixture_fetcher):
    p = BtcProvider(fixture_fetcher("btc_pages"), max_pages=3)
    txs, whole = p.txs(ADDR)
    assert len(txs) == 50 and whole is False
    txs, whole = p.txs(ADDR, pages=2)
    assert len(txs) == 72 and whole is True
    assert p.fee_share(ADDR, "not-a-transaction-it-read") == 0


def test_the_backend_is_blockstream_unless_told_otherwise(fixture_fetcher, monkeypatch):
    f = fixture_fetcher("btc_pages")
    assert BtcProvider(f).base == "https://mempool.space/api"       # the chain tests' setting
    monkeypatch.delenv("VASPFUSION_BTC_API")
    assert BtcProvider(f).base == "https://blockstream.info/api"
    assert BtcProvider(f, api="mempool.space").base == "https://mempool.space/api"
    with pytest.raises(ValueError, match="unknown Bitcoin API"):
        BtcProvider(f, api="example.org")


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


def test_a_history_that_cannot_be_read_back_to_since_returns_nothing(fixture_fetcher):
    """One page reaches back to some date. Asked for the transfers since an earlier one,
    the newest page is not an answer: the transfers nearest to `since` are the unread
    ones. Returning them made a trace hand money to payments made long afterwards."""
    first_page = next(iter(load_fixture("btc_pages")["responses"].values()))["body"]
    oldest_read = min(t["status"]["block_time"] for t in first_page)
    earlier = datetime.fromtimestamp(oldest_read - 86_400, tz=timezone.utc)
    p = BtcProvider(fixture_fetcher("btc_pages"), max_pages=1)
    rows = p.transfers(ADDR, "out", since=earlier, limit=500)
    assert rows == [] and rows.complete is False
    # with both pages read the same question has an answer
    rows = BtcProvider(fixture_fetcher("btc_pages"), max_pages=3).transfers(
        ADDR, "out", since=earlier, limit=500)
    assert rows and rows.complete is True and rows[0].block_time >= earlier
    # and a date inside the page that was read is answered from that page
    inside = datetime.fromtimestamp(oldest_read + 86_400, tz=timezone.utc)
    rows = BtcProvider(fixture_fetcher("btc_pages"), max_pages=1).transfers(
        ADDR, "out", since=inside, limit=500)
    assert rows.complete is True and all(r.block_time >= inside for r in rows)


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
    ("bitcoin", "BtcProvider"), ("solana", "SolanaProvider"), ("bsc", "EvmProvider"),
])
def test_registry(fixture_fetcher, chain, cls):
    assert type(get_provider(chain, fixture_fetcher("btc_pages"))).__name__ == cls


@pytest.mark.parametrize("chain", ["avalanche", "dogecoin"])
def test_registry_unsupported(fixture_fetcher, chain):
    with pytest.raises(UnsupportedChain):
        get_provider(chain, fixture_fetcher("btc_pages"))


def test_every_trace_chain_is_known():
    from typing import get_args

    from vaspfusion.api.schemas import TraceChain
    from vaspfusion.chains.addresses import EVM_FAMILY
    assert set(get_args(TraceChain)) <= set(EVM_FAMILY) | {"tron", "bitcoin", "solana"}
