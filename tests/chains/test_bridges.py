"""Bridge resolvers on recorded live answers (scripts/record_chain_fixtures.py). No network."""
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from chainfix import load_fixture
from vaspfusion.chains.base import Transfer, UnsupportedChain
from vaspfusion.chains.bridges import AcrossResolver, BridgeHop, Crossings, Unresolved
from vaspfusion.chains.cache import ChainCache, Fetcher

WALLET = "0x210297c6996b3008ed6ef0d4deb74b9515f364b0"
SPOKE = "0x5c7bcd6e7de5423a257d81b442095a1a6ced35c5"
BIG = "0xa72833c9a0c3f13cf1939a230adb33b01a29c8019629caf014c11b5509d50f3f"
SMALL = "0x60c782f004d2fd08ab7fc97ac2a5fc1be493536a84879371a1f97f9b2c239249"
NOT_ACROSS = "0x23922cd41aadb2ac494e52450a034a8a7726042056eaaceb2bc9169189aca636"


def deposit(tx_hash, chain="ethereum"):
    return Transfer(chain, tx_hash, datetime(2026, 6, 1, 2, 54, 59, tzinfo=timezone.utc), WALLET,
                    SPOKE, "USDT", Decimal(7800), Decimal(7800), None)


def test_a_filled_across_deposit_names_the_chain_recipient_and_payout(fixture_fetcher):
    hop = AcrossResolver(fixture_fetcher("across_filled")).resolve(deposit(BIG))
    assert hop == BridgeHop(
        bridge="Across", source_chain="ethereum", source_tx=BIG, dest_chain="base",
        dest_name="base", recipient=WALLET,
        payout_tx="0xae93232f3b2a28d7d0021df1d6c15cc23dc1a7f4f6cd4cd0fa565b11ceff955d",
        paid_at=datetime(2026, 6, 1, 2, 55, 53, tzinfo=timezone.utc),
        deposited_at=datetime(2026, 6, 1, 2, 54, 59, tzinfo=timezone.utc),
        source="app.across.to", token_out="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913")


def test_the_second_recorded_deposit_went_to_base_too(fixture_fetcher):
    hop = AcrossResolver(fixture_fetcher("across_filled")).resolve(deposit(SMALL))
    assert (hop.dest_chain, hop.recipient) == ("base", WALLET)
    assert hop.payout_tx == "0x302c38dae85698a31ea13536243d9b5a10826df17a39bdc38b47cb35bbea732f"
    assert int((hop.paid_at - hop.deposited_at).total_seconds()) == 8


def test_not_found_is_an_answer_and_replays_offline(fixture_fetcher):
    live = fixture_fetcher("across_unknown")
    said = AcrossResolver(live).resolve(deposit(NOT_ACROSS))
    assert said == Unresolved("Across' index holds no deposit for this transaction")
    assert live.stats["live"] == 1
    again = fixture_fetcher("across_unknown", offline=True)      # same cache file, no transport
    assert AcrossResolver(again).resolve(deposit(NOT_ACROSS)) == said
    assert again.stats == {"hits": 1, "live": 0, "retries": 0}


def test_offline_and_never_asked_is_unresolved_not_an_error(tmp_path):
    f = Fetcher(ChainCache(tmp_path / "c.duckdb"), None, offline=True)
    said = AcrossResolver(f).resolve(deposit(BIG))
    assert isinstance(said, Unresolved) and "could not be read" in said.reason


class _Answers:
    """A transport that answers the Across index with a body made from a recorded one."""

    def __init__(self, **change):
        body = next(iter(load_fixture("across_filled")["responses"].values()))["body"]
        self.body = {**body, "deposit": {**body["deposit"], **change}}
        self.calls = 0

    def get(self, url, params, headers):
        self.calls += 1
        return 200, json.dumps(self.body).encode()


def _fetcher(tmp_path, transport, name="c.duckdb"):
    return Fetcher(ChainCache(tmp_path / name), transport, offline=False,
                   sleep=lambda s: None)


def test_a_deposit_not_paid_out_yet_is_unresolved_and_is_asked_again(tmp_path):
    t = _Answers(status="pending", fillTx=None)
    f = _fetcher(tmp_path, t)
    assert isinstance(AcrossResolver(f).resolve(deposit(BIG)), Unresolved)
    AcrossResolver(f).resolve(deposit(BIG))
    assert t.calls == 2 and f.stats["hits"] == 0            # a pending answer is not kept


def test_a_refunded_deposit_did_not_cross(tmp_path):
    said = AcrossResolver(_fetcher(tmp_path, _Answers(status="refunded", fillTx=None))) \
        .resolve(deposit(BIG))
    assert said == Unresolved("Across reports the deposit as 'refunded', not paid out on "
                              "another chain")


def test_a_destination_with_no_adapter_is_named_not_traced(tmp_path):
    hop = AcrossResolver(_fetcher(tmp_path, _Answers(destinationChainId=59144))) \
        .resolve(deposit(BIG))
    assert (hop.dest_chain, hop.dest_name) == (None, "Linea")
    hop = AcrossResolver(_fetcher(tmp_path, _Answers(destinationChainId=2020), "d.duckdb")) \
        .resolve(deposit(BIG))
    assert (hop.dest_chain, hop.dest_name) == (None, "chain id 2020")


def test_across_is_not_asked_about_a_chain_it_has_no_id_for(tmp_path):
    f = Fetcher(ChainCache(tmp_path / "c.duckdb"), None, offline=False)   # would fail if called
    said = AcrossResolver(f).resolve(deposit(BIG, chain="tron"))
    assert said == Unresolved("Across is not asked about deposits on tron")


def test_crossings_picks_the_resolver_by_the_label_and_asks_once(fixture_fetcher):
    f = fixture_fetcher("across_filled")
    made = []
    cross = Crossings(f, lambda chain: made.append(chain) or f"provider:{chain}")
    first = cross.resolve("Across Protocol", deposit(BIG))
    assert cross.resolve("Across Protocol", deposit(BIG)) is first and f.stats["live"] == 1
    assert cross.resolve("Hop Protocol", deposit(BIG)) == Unresolved(
        "deposits into Hop Protocol cannot be matched to a payout by this tool")
    assert cross.provider("base") == cross.provider("base") == "provider:base" and made == ["base"]


def test_crossings_passes_on_that_a_chain_has_no_adapter(fixture_fetcher):
    def none(chain):
        raise UnsupportedChain(f"no adapter for chain {chain!r}")
    with pytest.raises(UnsupportedChain):
        Crossings(fixture_fetcher("across_filled"), none).provider("linea")
