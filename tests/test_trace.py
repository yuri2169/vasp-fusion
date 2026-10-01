"""The trace: follow a wallet's money forward (and its funding backward), allocating
by amount. Toy transfers, one rule per test (see tracekit.py)."""
from decimal import Decimal as D

import pytest

from tracekit import CHAIN, T0, ToyLabels, ToyProvider, tx
from vaspfusion.chains.base import ProviderError
from vaspfusion.trace import TraceConfig, trace

EX = {"HOT": ("ExA", "exchange", "hot", "curated")}


def run(transfers, labels=None, fail=(), **cfg):
    provider = ToyProvider(transfers, fail=fail)
    result = trace("S", CHAIN, provider, ToyLabels(labels if labels is not None else EX),
                   TraceConfig(**cfg))
    result.provider = provider
    return result


def out(result, address):
    return result.nodes[("outbound", address)]


# ------------------------------------------------------------------ forward
def test_straight_line_to_a_labelled_wallet():
    r = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "HOT", 1000, 5)])
    assert (r.asset, r.total_out) == ("USDT", D(1000))
    assert (out(r, "M1").state, out(r, "M1").hop) == ("expanded", 1)
    hot = out(r, "HOT")
    assert (hot.state, hot.hop, hot.received, hot.held) == ("labelled", 2, D(1000), D(1000))
    assert hot.label.entity == "ExA"
    assert [e.transfer.tx_hash for e in r.path_to("outbound", "HOT")] == ["tx1", "tx2"]


def test_a_labelled_wallet_is_not_expanded():
    r = run([tx(1, "S", "HOT", 500, 0), tx(2, "HOT", "COLD", 500, 1)])
    assert ("outbound", "COLD") not in r.nodes
    assert all(call[0] != "HOT" for call in r.provider.calls)


def test_a_split_gives_each_branch_its_share():
    r = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "HOT", 700, 5), tx(3, "M1", "X", 300, 6)])
    assert out(r, "HOT").received == D(700)
    assert out(r, "X").received == D(300)
    assert out(r, "M1").held == D(0)


def test_only_the_wallets_own_money_moves_on_through_a_commingled_wallet():
    # M1 forwards 5,000 in one transfer, but only 1,000 of it came from S
    r = run([tx(1, "S", "M1", 1000, 0), tx(2, "OTHER", "M1", 4000, 1),
             tx(3, "M1", "HOT", 5000, 5)])
    edge = r.path_to("outbound", "HOT")[-1]
    assert (edge.transfer.amount, edge.traced) == (D(5000), D(1000))
    assert out(r, "HOT").received == D(1000)


def test_first_out_after_arrival_takes_the_money_in_time_order():
    r = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "A", 600, 5), tx(3, "M1", "B", 600, 6),
             tx(4, "M1", "C", 600, 7)])
    assert out(r, "A").received == D(600)
    assert out(r, "B").received == D(400)
    assert ("outbound", "C") not in r.nodes


def test_money_that_did_not_move_on_is_held():
    r = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "HOT", 250, 5)])
    assert out(r, "M1").held == D(750)
    assert r.stopped["unspent"] == D(750)


def test_leftover_behind_a_cut_off_fetch_is_not_called_unspent():
    # M1 has more outflows than one fetch returns, so "did not move on" would be a guess
    r = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "A", 100, 5), tx(3, "M1", "B", 100, 6),
             tx(4, "M1", "HOT", 800, 7)], fetch_limit=2)
    assert out(r, "M1").held == D(800)
    assert r.stopped == {"unspent": D(200), "truncated": D(800)}


def test_an_outflow_before_the_money_arrived_is_not_its_destination():
    r = run([tx(1, "M1", "HOT", 1000, 0), tx(2, "S", "M1", 1000, 10)])
    assert ("outbound", "HOT") not in r.nodes
    assert out(r, "M1").held == D(1000)


def test_a_second_arrival_only_feeds_later_outflows():
    r = run([tx(1, "S", "M1", 100, 0), tx(2, "M1", "A", 500, 5), tx(3, "S", "M1", 900, 10),
             tx(4, "M1", "B", 500, 15)])
    assert out(r, "A").received == D(100)     # only the first 100 had arrived by then
    assert out(r, "B").received == D(500)
    assert out(r, "M1").held == D(400)


def test_a_hub_is_not_expanded():
    fan = [tx(10 + i, "HUB", f"U{i}", 10, 5 + i) for i in range(6)]
    r = run([tx(1, "S", "HUB", 1000, 0), *fan], hub_degree=5)
    hub = out(r, "HUB")
    assert (hub.state, hub.held) == ("hub", D(1000))
    assert not any(a.startswith("U") for _, a in r.nodes)
    assert r.stopped["hub"] == D(1000)


def test_the_hop_limit_stops_the_walk():
    chain_ = [tx(1, "S", "M1", 100, 0), tx(2, "M1", "M2", 100, 1), tx(3, "M2", "M3", 100, 2),
              tx(4, "M3", "HOT", 100, 3)]
    r = run(chain_, max_hops=3)
    assert (out(r, "M3").state, out(r, "M3").hop) == ("depth_limit", 3)
    assert ("outbound", "HOT") not in r.nodes
    assert out(run(chain_, max_hops=4), "HOT").hop == 4


def test_a_label_at_the_hop_limit_still_counts():
    r = run([tx(1, "S", "M1", 100, 0), tx(2, "M1", "HOT", 100, 1)], max_hops=2)
    assert out(r, "HOT").state == "labelled"


def test_dust_and_unknown_tokens_are_ignored():
    r = run([tx(1, "S", "M1", 1000, 0), tx(2, "S", "POISON", "0.000001", 1),
             tx(3, "S", "SPOOF", 1000, 2, asset="USDT@fake-contract"),
             tx(4, "S", "ZERO", 0, 3)])
    assert r.total_out == D(1000)
    assert {a for side, a in r.nodes if side == "outbound"} == {"M1"}


def test_money_that_comes_back_to_the_wallet_stops_there():
    r = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "S", 400, 5), tx(3, "M1", "HOT", 600, 6),
             tx(4, "S", "ELSEWHERE", 400, 9)])
    assert r.stopped["returned"] == D(400)
    assert out(r, "HOT").received == D(600)


def test_a_wallet_reached_twice_does_not_double_count_its_outflow():
    # 500 reaches M2 directly and 500 through M1; M2 only ever sent 600 on
    r = run([tx(1, "S", "M2", 500, 0), tx(2, "S", "M1", 500, 1), tx(3, "M1", "M2", 500, 2),
             tx(4, "M2", "HOT", 600, 10)], max_hops=4)
    assert out(r, "HOT").received == D(600)
    assert out(r, "M2").held == D(400)
    assert out(r, "M2").hop == 1              # nearest route wins


def test_wallets_holding_too_little_are_not_expanded():
    r = run([tx(1, "S", "BIG", 995, 0), tx(2, "S", "TINY", 5, 1), tx(3, "TINY", "HOT", 5, 2),
             tx(4, "BIG", "HOT", 995, 3)], min_share=D("0.01"))
    assert out(r, "TINY").state == "small"
    assert out(r, "HOT").received == D(995)
    assert all(call[0] != "TINY" for call in r.provider.calls)


def test_the_budget_goes_to_the_wallets_holding_the_most():
    r = run([tx(1, "S", "A", 100, 0), tx(2, "S", "B", 900, 1), tx(3, "A", "HOT", 100, 5),
             tx(4, "B", "HOT", 900, 6)], max_nodes=1)
    assert (out(r, "B").state, out(r, "A").state) == ("expanded", "budget")
    assert out(r, "HOT").received == D(900)


def test_a_failing_wallet_is_marked_and_the_trace_goes_on():
    r = run([tx(1, "S", "A", 400, 0), tx(2, "S", "B", 600, 1), tx(3, "B", "HOT", 600, 5)],
            fail={"A"})
    assert out(r, "A").state == "error" and "upstream failed" in out(r, "A").note
    assert out(r, "HOT").received == D(600)


def test_a_failure_at_the_wallet_itself_is_raised():
    with pytest.raises(ProviderError):
        run([tx(1, "S", "A", 400, 0)], fail={"S"})


@pytest.mark.parametrize("transfers", [
    [tx(1, "S", "M1", 1000, 0), tx(2, "M1", "HOT", 700, 5), tx(3, "M1", "X", 200, 6)],
    [tx(1, "S", "M2", 500, 0), tx(2, "S", "M1", 500, 1), tx(3, "M1", "M2", 500, 2),
     tx(4, "M2", "HOT", 600, 10), tx(5, "M2", "S", 50, 11)],
    [tx(1, "S", "HUB", 10, 0), *[tx(10 + i, "HUB", f"U{i}", 1, 5 + i) for i in range(40)]],
])
def test_every_unit_the_wallet_sent_is_accounted_for(transfers):
    r = run(transfers, max_hops=4)
    assert sum(r.stopped.values()) == r.total_out
    assert sum(n.held for (side, _), n in r.nodes.items() if side == "outbound") \
        + r.stopped.get("returned", D(0)) == r.total_out


# ------------------------------------------------------------------ which asset
def test_the_stablecoin_with_the_largest_outflow_is_followed():
    r = run([tx(1, "S", "A", 100, 0, asset="USDC"), tx(2, "S", "B", 900, 1),
             tx(3, "S", "C", 50, 2, asset="COIN")])
    assert (r.asset, r.total_out) == ("USDT", D(900))
    assert r.untraced == {"USDC": (1, D(100)), "COIN": (1, D(50))}
    assert {a for side, a in r.nodes if side == "outbound"} == {"B"}


def test_the_native_coin_is_followed_when_no_stablecoin_was_sent():
    r = run([tx(1, "S", "M1", 3, 0, asset="COIN"), tx(2, "M1", "HOT", 3, 1, asset="COIN"),
             tx(3, "M1", "ELSE", 3, 2, asset="USDT")])
    assert (r.asset, r.total_out) == ("COIN", D(3))
    assert out(r, "HOT").received == D(3)
    assert ("outbound", "ELSE") not in r.nodes     # another asset is not this money


def test_a_wallet_that_sent_nothing_has_an_empty_trace():
    r = run([tx(1, "X", "S", 100, 0)])
    assert (r.asset, r.total_out) == (None, D(0))
    assert not [k for k in r.nodes if k[0] == "outbound"]


def test_hitting_the_fetch_limit_at_the_wallet_is_reported():
    r = run([tx(i, "S", f"A{i}", 10, i) for i in range(1, 8)], fetch_limit=5)
    assert r.truncated and r.total_out == D(50)
    assert any("first 5" in n for n in r.notes)


def test_since_limits_the_wallets_own_transfers():
    from datetime import timedelta
    r = run([tx(1, "S", "OLD", 100, 0), tx(2, "S", "NEW", 100, 60)],
            since=T0 + timedelta(minutes=30))
    assert {a for side, a in r.nodes if side == "outbound"} == {"NEW"}


def test_a_labelled_exchange_wallet_is_not_traced_at_all():
    r = run([tx(1, "S", "A", 100, 0)], labels={"S": ("ExA", "exchange", "hot")})
    assert r.origin_label.entity == "ExA"
    assert r.provider.calls == [] and r.total_out == D(0)


def test_a_sanctioned_wallet_is_still_traced():
    r = run([tx(1, "S", "HOT", 100, 0)],
            labels={"S": ("OFAC SDN", "sanctioned"), **EX})
    assert r.origin_label.category == "sanctioned"
    assert out(r, "HOT").received == D(100)


# ------------------------------------------------------------------ backward
def inn(result, address):
    return result.nodes[("inbound", address)]


def test_direct_funders_with_their_amounts():
    r = run([tx(1, "HOT", "S", 300, 0), tx(2, "F1", "S", 700, 1), tx(3, "S", "A", 1000, 5)])
    assert (r.in_asset, r.total_in) == ("USDT", D(1000))
    assert (inn(r, "HOT").state, inn(r, "HOT").received, inn(r, "HOT").hop) == \
        ("labelled", D(300), 1)
    assert (inn(r, "F1").state, inn(r, "F1").received) == ("depth_limit", D(700))
    assert [e.transfer.tx_hash for e in r.path_to("inbound", "HOT")] == ["tx1"]


def test_funders_are_not_expanded_by_default():
    r = run([tx(1, "G", "F1", 700, 0), tx(2, "F1", "S", 700, 1)])
    assert ("inbound", "G") not in r.nodes
    assert all(call[0] == "S" for call in r.provider.calls)


def test_two_hops_back_uses_the_latest_inflows_before_the_payment():
    r = run([tx(1, "HOT", "F1", 500, 0), tx(2, "G", "F1", 400, 1), tx(3, "F1", "S", 600, 5),
             tx(4, "LATE", "F1", 999, 9)], inbound_hops=2)
    # 600 left F1 at minute 5: the 400 from G (minute 1) and 200 of the 500 from HOT
    assert inn(r, "G").received == D(400)
    assert (inn(r, "HOT").received, inn(r, "HOT").hop) == (D(200), 2)
    assert ("inbound", "LATE") not in r.nodes
    assert [e.transfer.tx_hash for e in r.path_to("inbound", "HOT")] == ["tx1", "tx3"]


def test_a_funder_with_an_incomplete_history_is_not_expanded():
    ins = [tx(10 + i, f"G{i}", "F1", 10, i) for i in range(5)]
    r = run([*ins, tx(1, "F1", "S", 50, 30)], inbound_hops=2, fetch_limit=5, hub_degree=99)
    assert inn(r, "F1").state == "truncated"
    assert not any(a.startswith("G") for _, a in r.nodes)


# ------------------------------------------------------------------ graph
def test_igraph_holds_every_traced_transfer():
    r = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "HOT", 700, 5), tx(3, "M1", "X", 300, 6),
             tx(4, "F1", "S", 1000, -5)])
    g = r.to_igraph()
    assert set(g.vs["name"]) == {"S", "M1", "HOT", "X", "F1"}
    assert g.ecount() == 4 and g.is_directed()
    s, hot = g.vs.find(name="S").index, g.vs.find(name="HOT").index
    assert g.distances(s, hot, mode="out")[0][0] == 2
    assert g.vs.find(name="HOT")["entity"] == "ExA"
    assert sorted(g.es["traced"]) == [300.0, 700.0, 1000.0, 1000.0]


def test_the_same_inputs_give_the_same_trace():
    transfers = [tx(1, "S", "M1", 1000, 0), tx(2, "M1", "HOT", 700, 5), tx(3, "M1", "X", 300, 5),
                 tx(4, "S", "M2", 1000, 0), tx(5, "M2", "HOT", 1000, 5)]
    a, b = run(transfers), run(list(reversed(transfers)))
    assert [(e.transfer.tx_hash, e.traced, e.hop) for e in a.edges] == \
        [(e.transfer.tx_hash, e.traced, e.hop) for e in b.edges]
    assert list(a.nodes) == list(b.nodes)
