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


# ------------------------------------------------------------------ Stargate over LayerZero (E6)
# Real deposits of 7 Oct 2026: USDT into Stargate's pool on Ethereum, delivered on BNB Chain.
from vaspfusion.chains.bridges import (LayerZeroResolver, WormholeResolver,  # noqa: E402
                                       stargate_recipient)

SG_POOL = "0x933597a323eb81cae705c5bc29985172fd5a3973"
SG_A = "0x0443506c46795eef7141c016df18a918a45405b0cfb86e6609005703213a0645"
SG_B = "0x5db177c6873979a0c0f6470efecc068d4d4ed0d126d8b514d8cf3cfe0a04ca9c"
WH_PAID = "0x8b70bbcf3eab77075c8acaf9cee475f82ab0a8e5b2ff00a01568784ba31e0eaf"
WH_WAITING = "0x485ea928400d369d7040f306d489763ad2a59e48179b2c1f8d87db976eaf1fd4"


def test_a_delivered_stargate_deposit_names_the_chain_recipient_and_payout(fixture_fetcher):
    hop = LayerZeroResolver(fixture_fetcher("layerzero_delivered")).resolve(deposit(SG_A))
    assert hop == BridgeHop(
        bridge="Stargate", source_chain="ethereum", source_tx=SG_A, dest_chain="bsc",
        dest_name="bsc", recipient="0x54776446aa29fc49d152b4850bd410ea1e4d24bf",
        payout_tx="0x690699a7b40eec4d325420fb0c94ba5b5fa1aaddc0b9a0364953a357c71c37e5",
        paid_at=datetime(2026, 10, 7, 17, 35, 46, tzinfo=timezone.utc),
        deposited_at=datetime(2026, 10, 7, 17, 32, 23, tzinfo=timezone.utc),
        source="scan.layerzero-api.com")


def test_the_recipient_is_the_one_the_message_names_not_whoever_paid_the_pool(fixture_fetcher):
    """The second recorded deposit reached the pool from a router; the message names the
    person's own address, and that is who the trace goes on from."""
    hop = LayerZeroResolver(fixture_fetcher("layerzero_delivered")).resolve(deposit(SG_B))
    assert hop.recipient == "0x2fb621a98a77ebc525ae88fe9760ddf3ed4cc83d"
    assert hop.dest_chain == "bsc" and int((hop.paid_at - hop.deposited_at).total_seconds()) == 203


def test_no_layerzero_message_is_an_answer_and_replays_offline(fixture_fetcher):
    live = fixture_fetcher("layerzero_unknown")
    said = LayerZeroResolver(live).resolve(deposit(NOT_ACROSS))
    assert isinstance(said, Unresolved) and "holds no message for this transaction" in said.reason
    again = fixture_fetcher("layerzero_unknown", offline=True)
    assert LayerZeroResolver(again).resolve(deposit(NOT_ACROSS)) == said
    assert again.stats == {"hits": 1, "live": 0, "retries": 0}


class _Message:
    """LayerZero Scan answering with a recorded message, changed."""

    def __init__(self, change):
        body = next(iter(load_fixture("layerzero_delivered")["responses"].values()))["body"]
        self.body = json.loads(json.dumps(body))
        change(self.body["data"][0])
        self.calls = 0

    def get(self, url, params, headers):
        self.calls += 1
        return 200, json.dumps(self.body).encode()


def test_a_message_still_on_its_way_is_unresolved_and_is_asked_again(tmp_path):
    t = _Message(lambda m: m["status"].update(name="INFLIGHT"))
    f = _fetcher(tmp_path, t)
    assert isinstance(LayerZeroResolver(f).resolve(deposit(SG_A)), Unresolved)
    LayerZeroResolver(f).resolve(deposit(SG_A))
    assert t.calls == 2 and f.stats["hits"] == 0


def test_a_message_that_is_not_a_stargate_transfer_names_nobody(tmp_path):
    t = _Message(lambda m: m["source"]["tx"].update(payload="0x02" + "00" * 60))
    said = LayerZeroResolver(_fetcher(tmp_path, t)).resolve(deposit(SG_A))
    assert said == Unresolved("the LayerZero message is not a Stargate transfer to one "
                              "recipient, so it does not say who was paid")


def test_a_layerzero_destination_with_no_adapter_is_named_not_traced(tmp_path):
    def away(m):
        m["pathway"]["dstEid"] = 30332
        m["pathway"]["receiver"]["chain"] = "sonic"
    hop = LayerZeroResolver(_fetcher(tmp_path, _Message(away))).resolve(deposit(SG_A))
    assert (hop.dest_chain, hop.dest_name) == (None, "sonic")


def test_the_stargate_message_layout():
    to = "54776446aa29fc49d152b4850bd410ea1e4d24bf"
    assert stargate_recipient("0x01" + "0002" + "00" * 12 + to + "000000000074f3ff") == "0x" + to
    assert stargate_recipient("0x01" + "0002" + "11" * 12 + to + "000000000074f3ff") is None
    assert stargate_recipient("0x0100") is None and stargate_recipient(None) is None


# ------------------------------------------------------------------ Wormhole's token bridge (E6)
def test_a_redeemed_wormhole_transfer_names_the_chain_recipient_and_payout(fixture_fetcher):
    """A real transfer of 7 Oct 2026: 1,442 USDT from Ethereum, redeemed on Kaia, a chain
    this tool has no adapter for. It is matched and named, not followed."""
    hop = WormholeResolver(fixture_fetcher("wormhole_paid")).resolve(deposit(WH_PAID))
    assert hop == BridgeHop(
        bridge="Wormhole", source_chain="ethereum", source_tx=WH_PAID, dest_chain=None,
        dest_name="Kaia (Klaytn)", recipient="0xf5aa070ba5e641923163fa6c12169b070a0a1504",
        payout_tx="0x6aecf074ac3c685e9c8b54c2eb0dc5154e438670eb036c5eb390f98244bba790",
        paid_at=datetime(2026, 10, 7, 11, 3, 22, tzinfo=timezone.utc),
        deposited_at=datetime(2026, 10, 7, 10, 45, 59, tzinfo=timezone.utc),
        source="api.wormholescan.io")


def test_a_wormhole_transfer_nobody_redeemed_is_unresolved_and_is_asked_again(fixture_fetcher):
    f = fixture_fetcher("wormhole_waiting")
    said = WormholeResolver(f).resolve(deposit(WH_WAITING))
    assert isinstance(said, Unresolved) and "has not been paid out" in said.reason
    WormholeResolver(f).resolve(deposit(WH_WAITING))
    assert f.stats["hits"] == 0 and f.transport.calls >= 2     # not kept: asked each time


def test_no_wormhole_transfer_is_an_answer_and_replays_offline(fixture_fetcher):
    live = fixture_fetcher("wormhole_unknown")
    said = WormholeResolver(live).resolve(deposit(NOT_ACROSS))
    assert said == Unresolved("Wormholescan holds no transfer for this transaction")
    again = fixture_fetcher("wormhole_unknown", offline=True)
    assert WormholeResolver(again).resolve(deposit(NOT_ACROSS)) == said


def test_each_bridge_label_has_its_resolver_and_the_rest_are_only_flagged(fixture_fetcher):
    f = fixture_fetcher("layerzero_delivered", "wormhole_paid")
    cross = Crossings(f, lambda chain: None)
    assert cross.resolve("Stargate", deposit(SG_A)).bridge == "Stargate"
    assert cross.resolve("Stargate Finance", deposit(SG_A)).bridge == "Stargate"
    assert cross.resolve("Wormhole", deposit(WH_PAID)).bridge == "Wormhole"
    said = cross.resolve("Hop Protocol", deposit(SG_A))
    assert said == Unresolved("deposits into Hop Protocol cannot be matched to a payout by "
                              "this tool")
