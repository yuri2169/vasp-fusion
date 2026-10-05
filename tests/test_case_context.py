"""The context of a case: the transfers its trace read and did not follow. It is worked
out by tracing the wallet again from the recorded responses, and it never changes the
case. Recorded demo wallets; no network."""
import copy

import pytest

from demokit import DemoLabels, SPECS, demo_fetcher, run_demo
from vaspfusion.api import schemas as S
from vaspfusion.context import case_context

OPTS = {"key": "test-key"}


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    root = tmp_path_factory.mktemp("context")
    out = {}
    for case_id in ("tron-coindcx", "tron-abstain", "eth-bridge", "btc-htx"):
        cache = root / f"{case_id}.duckdb"
        out[case_id] = (run_demo(case_id, cache), cache)
    return out


def context(recorded, case_id, wallet=None, online=False, **kw):
    case, cache = recorded[case_id]
    replay = demo_fetcher(cache, case_id, offline=True)
    fetcher = demo_fetcher(cache, case_id, offline=not online)
    return case_context(case, replay, DemoLabels(), wallet=wallet, fetcher=fetcher, **OPTS, **kw)


def graph_keys(case):
    return {(e["tx_hash"], e["source"], e["target"], e["asset"], e["amount"])
            for e in case["graph"]["edges"]}


@pytest.mark.parametrize("case_id", ["tron-coindcx", "tron-abstain", "eth-bridge", "btc-htx"])
def test_the_whole_context_is_what_was_seen_and_not_followed(recorded, case_id):
    case = recorded[case_id][0]
    ctx = S.CaseContext.model_validate(context(recorded, case_id)).model_dump(mode="json")
    s = case["trace_summary"]
    assert ctx["transfers"] == s["transfers_seen"] - s["transfers_followed"]
    assert len(ctx["edges"]) == ctx["transfers"] and ctx["truncated"] is False
    assert (ctx["recorded"], ctx["wallet"], ctx["case_id"]) == (True, None, case["id"])
    # none of it is on the graph, and every transfer is there once
    keys = [(e["tx_hash"], e["source"], e["target"], e["asset"], e["amount"]) for e in ctx["edges"]]
    assert len(keys) == len(set(keys)) and not set(keys) & graph_keys(case)
    # every end of every transfer is a node, and the ones on the graph say so
    ids = {n["id"] for n in ctx["nodes"]}
    assert {end for e in ctx["edges"] for end in (e["source"], e["target"])} <= ids | set()
    on_graph = {n["id"] for n in case["graph"]["nodes"]}
    assert {n["id"] for n in ctx["nodes"] if n["on_graph"]} == ids & on_graph


def test_asking_for_context_changes_nothing_about_the_case(recorded):
    case = recorded["tron-abstain"][0]
    before = copy.deepcopy(case)
    context(recorded, "tron-abstain")
    assert case == before


def test_one_wallets_context_is_its_own_transfers_only(recorded):
    case = recorded["tron-abstain"][0]
    whole = context(recorded, "tron-abstain")
    read = [n["id"] for n in case["graph"]["nodes"] if n["role"] in ("suspect", "intermediary", "hub")]
    total = 0
    for wallet in read:
        ctx = context(recorded, "tron-abstain", wallet=wallet)
        assert ctx["recorded"] is True and ctx["wallet"] == wallet
        assert all(wallet in (e["source"], e["target"]) for e in ctx["edges"])
        mine = [e for e in whole["edges"] if wallet in (e["source"], e["target"])]
        assert ctx["transfers"] == len(mine)
        total += ctx["transfers"]
    assert total >= whole["transfers"]      # a transfer between two read wallets is in both


def test_dust_is_named_as_dust(recorded):
    ctx = context(recorded, "tron-coindcx")
    why = {e["why"] for e in ctx["edges"]}
    assert "dust" in why and why <= {"dust", "other_asset", "not_traced"}
    assert sum(e["why"] == "dust" for e in ctx["edges"]) == \
        recorded["tron-coindcx"][0]["trace_summary"]["transfers_dust"]


def test_a_wallet_that_was_not_read_is_not_recorded_offline(recorded):
    case = recorded["tron-coindcx"][0]
    unread = next(n["id"] for n in case["graph"]["nodes"] if n["label"] is not None)
    ctx = context(recorded, "tron-coindcx", wallet=unread)
    assert (ctx["recorded"], ctx["edges"], ctx["transfers"]) == (False, [], 0)
    assert "not recorded" in ctx["reason"]
    assert ctx["live"] is False


def test_a_wallet_that_is_not_part_of_the_case_is_refused(recorded):
    with pytest.raises(KeyError):
        context(recorded, "tron-coindcx", wallet="TNotAWalletOfThisCase")


def test_a_long_context_is_cut_and_says_so(recorded):
    whole = context(recorded, "tron-abstain")
    cut = context(recorded, "tron-abstain", limit=50)
    assert (len(cut["edges"]), cut["truncated"], cut["transfers"]) == (50, True, whole["transfers"])
    ends = {end for e in cut["edges"] for end in (e["source"], e["target"])}
    assert {n["id"] for n in cut["nodes"]} == ends


def test_the_same_context_every_time(recorded):
    assert context(recorded, "eth-bridge") == context(recorded, "eth-bridge")
    assert set(SPECS) >= {"eth-bridge"}


# ------------------------------------------------------------------ a wallet the trace did not read
def test_an_unread_wallets_listing_is_fetched_and_what_is_on_the_graph_is_left_out():
    from tracekit import CHAIN, ToyLabels, ToyProvider, tx
    from vaspfusion.context import _unread
    from vaspfusion.trace import TraceConfig, trace
    rows = [tx(1, "S", "HOT", 1000, 0), tx(2, "HOT", "COLD", 700, 5), tx(3, "Z", "HOT", 40, 9)]
    provider = ToyProvider(rows)
    tr = trace("S", CHAIN, provider, ToyLabels({"HOT": ("ExA", "exchange", "hot", "curated")}),
               TraceConfig(inbound_hops=0))
    assert "HOT" not in tr.read                      # labelled: the trail ends there
    got = _unread(tr, "HOT", None, lambda chain: provider)
    # its other transfers, both ways; the one that brought the wallet's money is on the graph
    assert sorted(t.tx_hash for t in got) == ["tx2", "tx3"]
