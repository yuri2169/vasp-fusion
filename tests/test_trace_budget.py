"""The trace budget: wallets, depth and time. The officer can raise it; whatever it is,
it is spent on the wallets holding the most, and the result says when it, not the
evidence, ended the walk. Toy transfers (tracekit.py)."""
from decimal import Decimal as D

import pytest

from tracekit import CHAIN, ToyLabels, ToyProvider, tx
from vaspfusion.trace import (DEFAULT_WALLETS, MAX_WALLETS, TraceConfig, replay_config,
                              trace)

EX = {"HOT": ("ExA", "exchange", "hot", "curated")}
# S pays five wallets, each of which passes everything on to the exchange a minute later
FAN = [("A", 50), ("B", 100), ("C", 150), ("D", 300), ("E", 400)]
TRANSFERS = [tx(i, "S", w, amount, i) for i, (w, amount) in enumerate(FAN, 1)] + \
            [tx(10 + i, w, "HOT", amount, 10 + i) for i, (w, amount) in enumerate(FAN, 1)]


class Ticks:
    """A clock that moves one second every time it is read."""

    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


def run(clock=None, **cfg):
    kw = {"clock": clock} if clock else {}
    return trace("S", CHAIN, ToyProvider(TRANSFERS), ToyLabels(EX),
                 TraceConfig(inbound_hops=0, **cfg), **kw)


def states(r) -> dict[str, str]:
    return {a: n.state for (side, a), n in r.nodes.items() if side == "outbound" and a != "HOT"}


def shape(r):
    return (states(r), dict(r.stopped), sorted((e.transfer.tx_hash, e.traced, e.hop)
                                               for e in r.edges))


def test_the_default_budget_is_the_one_every_recorded_case_was_traced_with():
    assert TraceConfig().max_nodes == DEFAULT_WALLETS == 40
    assert TraceConfig().max_seconds is None and TraceConfig().stop_after is None


def test_within_the_budget_nothing_is_said_about_it():
    r = run()
    assert set(states(r).values()) == {"expanded"}
    assert r.budget_ended == {} and r.stopped == {"labelled": D(1000)}
    assert r.expanded("outbound") == 5 and r.seconds is None


@pytest.mark.parametrize("budget, read", [(1, "E"), (2, "ED"), (3, "EDC"), (4, "EDCB")])
def test_the_budget_is_spent_on_the_wallets_holding_the_most(budget, read):
    r = run(max_nodes=budget)
    assert {a for a, s in states(r).items() if s == "expanded"} == set(read)
    assert {a for a, s in states(r).items() if s == "budget"} == set("ABCDE") - set(read)
    left = sum(D(amount) for w, amount in FAN if w not in read)
    assert r.budget_ended == {"outbound": "wallets"}
    assert r.stopped == {"labelled": D(1000) - left, "budget": left}


def test_a_larger_budget_follows_more_of_the_money():
    reached = [run(max_nodes=n).stopped["labelled"] for n in (1, 2, 3, 4, 5)]
    assert reached == [D(400), D(700), D(850), D(950), D(1000)]


def test_the_wallet_budget_has_bounds():
    assert TraceConfig(max_nodes=MAX_WALLETS).max_nodes == 2000
    for bad in (0, -1, MAX_WALLETS + 1):
        with pytest.raises(ValueError, match="wallet budget"):
            TraceConfig(max_nodes=bad)
    with pytest.raises(ValueError, match="time budget"):
        TraceConfig(max_seconds=0)


def test_a_time_budget_ends_the_walk_and_says_where():
    r = run(clock=Ticks(), max_seconds=2.5)      # two wallets are asked for, then time is up
    assert states(r) == {"E": "expanded", "D": "expanded", "C": "budget", "B": "budget",
                         "A": "budget"}
    assert r.budget_ended == {"outbound": "time"} and r.stopped_after == {"outbound": 2}
    assert r.stopped == {"labelled": D(700), "budget": D(300)}
    assert r.seconds is not None and r.seconds >= 2.5


def test_time_that_does_not_run_out_changes_nothing():
    assert shape(run(max_seconds=3600)) == shape(run())
    assert run(max_seconds=3600).budget_ended == {} == run(max_seconds=3600).stopped_after


def test_a_time_limited_trace_is_replayed_exactly_without_a_clock():
    cfg = TraceConfig(inbound_hops=0, max_seconds=2.5)
    first = trace("S", CHAIN, ToyProvider(TRANSFERS), ToyLabels(EX), cfg, clock=Ticks())
    again_cfg = replay_config(cfg, first)
    assert (again_cfg.max_seconds, again_cfg.stop_after) == (2.5, (2, None))
    again = trace("S", CHAIN, ToyProvider(TRANSFERS), ToyLabels(EX), again_cfg)
    assert shape(again) == shape(first)
    assert again.budget_ended == {"outbound": "time"} and again.stopped_after == {"outbound": 2}
    assert again.seconds is None                    # no clock was read


def test_a_trace_no_clock_ended_is_its_own_replay():
    cfg = TraceConfig(inbound_hops=0, max_nodes=2)
    assert replay_config(cfg, run(max_nodes=2)) is cfg
    timed = TraceConfig(inbound_hops=0, max_seconds=3600)
    done = trace("S", CHAIN, ToyProvider(TRANSFERS), ToyLabels(EX), timed)
    # a time limit that did not bite: replayed with the clock off and no stop
    assert replay_config(timed, done) == TraceConfig(inbound_hops=0, max_seconds=3600,
                                                     stop_after=(None, None))


def test_time_running_out_before_the_first_wallet_reads_none():
    r = run(clock=Ticks(), max_seconds=0.5)
    assert set(states(r).values()) == {"budget"} and r.stopped_after == {"outbound": 0}
    again = trace("S", CHAIN, ToyProvider(TRANSFERS), ToyLabels(EX),
                  replay_config(TraceConfig(inbound_hops=0, max_seconds=0.5), r))
    assert shape(again) == shape(r)


def test_the_inbound_side_has_the_same_budget():
    funders = [tx(20 + i, f"F{i}", "S", 100 * i, i) for i in (1, 2, 3)] + \
              [tx(30 + i, f"G{i}", f"F{i}", 100 * i, 0) for i in (1, 2, 3)]
    r = trace("S", CHAIN, ToyProvider(TRANSFERS + funders), ToyLabels(EX),
              TraceConfig(inbound_hops=2, max_nodes=2))
    inbound = {a: n.state for (side, a), n in r.nodes.items() if side == "inbound"}
    assert (inbound["F3"], inbound["F2"], inbound["F1"]) == ("expanded", "expanded", "budget")
    assert r.budget_ended == {"outbound": "wallets", "inbound": "wallets"}
