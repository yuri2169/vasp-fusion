"""Gas events (who covered an address's network fee) from recorded real listings."""
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from discoverkit import replay_fetcher
from vaspfusion.chains.evm import EvmProvider
from vaspfusion.chains.tron import TronProvider

SINCE = datetime(2026, 9, 17, tzinfo=timezone.utc)
KUCOIN_DEP = "TD9MoA86kzLmYBENwHNjDN4vmFpXMZjBT7"
COINDCX_DEP = "TTTZH6nWX8tk1b73xHfCJk3x9aBRgWbeEK"
KUCOIN_ENERGY = "TJGv1jeHA8QxZ5jjwY8wc4PQ2GHg4772L8"     # labelled KuCoin (proof of reserves)
KUCOIN_TRX = "TCSN2TXGLi3KnLTtMY2ch3Hh8jwUtotkYF"        # labelled KuCoin (proof of reserves)
COINDCX_10 = "TFLxNHunhEizmeEdiMyA3r2XGLSKaEznGd"        # labelled "CoinDCX 10"


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch, tmp_path):
    monkeypatch.delenv("OFFLINE", raising=False)
    for k in ("TRONGRID_API_KEY", "ETHERSCAN_API_KEY"):
        monkeypatch.setenv(k, "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")


def tron(tmp_path, **kw):
    return TronProvider(replay_fetcher(tmp_path, "tron_gas", **kw), page_size=50, max_pages=1)


def test_an_energy_delegation_to_the_address_names_the_delegator(tmp_path):
    events = tron(tmp_path).gas_events(KUCOIN_DEP, since=SINCE)
    energy = [e for e in events if e.kind == "energy"]
    assert [e.payer for e in energy] == [KUCOIN_ENERGY]
    assert energy[0].time.tzinfo is not None and energy[0].amount is None


def test_a_trx_top_up_names_the_sender_and_the_amount(tmp_path):
    events = tron(tmp_path).gas_events(KUCOIN_DEP, since=SINCE)
    native = [e for e in events if e.kind == "native"]
    assert [(e.payer, e.amount) for e in native] == [(KUCOIN_TRX, D(15))]


def test_coindcx_tops_up_with_trx_and_delegates_nothing(tmp_path):
    events = tron(tmp_path).gas_events(COINDCX_DEP, since=SINCE)
    assert {(e.kind, e.payer, e.amount) for e in events} == {("native", COINDCX_10, D(15))}


def test_poisoning_dust_and_undelegations_are_not_gas(tmp_path):
    # the listings hold TRX transfers of under 1 TRX and UnDelegateResource rows
    events = tron(tmp_path).gas_events(KUCOIN_DEP, since=SINCE)
    assert all(e.kind != "native" or e.amount >= 1 for e in events)
    assert all(e.payer != KUCOIN_DEP for e in events)
    assert len(events) == 2 and events == sorted(events, key=lambda e: (e.time, e.tx_hash))


def test_gas_events_replay_offline_from_the_cache(tmp_path):
    live = tron(tmp_path).gas_events(KUCOIN_DEP, since=SINCE)
    offline = tron(tmp_path, offline=True).gas_events(KUCOIN_DEP, since=SINCE)
    assert offline == live


def test_the_default_adapter_reports_native_top_ups(tmp_path):
    # Bitget deposit address on Ethereum (tests/fixtures/chains/eth_etherscan.json): the
    # exchange's hot wallet sends it ETH for gas before a sweep
    p = EvmProvider("ethereum", replay_fetcher(tmp_path, "eth_etherscan"), page_size=3,
                    key="test-key")
    events = p.gas_events("0x000483c56fe99127fbd62da5d8b899a159116dc1", limit=5)
    assert events and all(e.kind == "native" and e.amount > 0 for e in events)
    assert all(e.payer != "0x000483c56fe99127fbd62da5d8b899a159116dc1" for e in events)
