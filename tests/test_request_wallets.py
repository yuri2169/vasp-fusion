"""What a request to an exchange lists: one row per wallet, each with its own amount.
Toy transfers (tracekit.py). Review finding C1: the whole sum must never sit on one wallet."""
from decimal import Decimal as D

from tracekit import CHAIN, ToyLabels, ToyProvider, tx
from vaspfusion.attribute.rules import attribute
from vaspfusion.trace import TraceConfig, trace

LABELS = {
    "HOT1": ("ExA", "exchange", "hot", "curated"),
    "HOT2": ("ExA", "exchange", "hot", "published_por"),
    "DEP": ("ExA", "exchange", "deposit", "derived"),
}


def rows(transfers, labels=LABELS, origin="S"):
    tr = trace(origin, CHAIN, ToyProvider(transfers), ToyLabels(labels), TraceConfig())
    (c,) = [c for c in attribute(tr).candidates if c.direction == "outbound"]
    assert sum((w["amount"] for w in c.request_wallets), D(0)) == c.amount
    return c.request_wallets


def brief(ws):
    return [(w["address"], w["amount"], w["paid_into"], w["tier"], w["tx_hashes"]) for w in ws]


def test_two_exchange_wallets_are_two_rows_each_with_its_own_sum():
    ws = rows([tx(1, "S", "HOT1", 700, 0), tx(2, "S", "HOT2", 300, 5)])
    assert brief(ws) == [("HOT1", D(700), None, "curated", ["tx1"]),
                         ("HOT2", D(300), None, "published_por", ["tx2"])]


def test_two_wallets_that_each_passed_everything_on_are_both_named():
    ws = rows([tx(1, "S", "X", 400, 0), tx(2, "S", "Y", 600, 1),
               tx(3, "X", "HOT1", 400, 10), tx(4, "Y", "HOT1", 600, 11)])
    assert brief(ws) == [("Y", D(600), "HOT1", "curated", ["tx2", "tx4"]),
                         ("X", D(400), "HOT1", "curated", ["tx1", "tx3"])]
    assert [w["reached_at"].minute for w in ws] == [1, 0]      # when the money reached X, Y


def test_a_wallet_that_kept_part_is_not_named_the_exchange_wallet_is():
    ws = rows([tx(1, "S", "X", 1000, 0), tx(2, "X", "HOT1", 600, 10), tx(3, "X", "Z", 400, 11)])
    assert brief(ws) == [("HOT1", D(600), None, "curated", ["tx2"])]


def test_a_labelled_deposit_address_is_named_itself_even_when_reached_through_a_wallet():
    ws = rows([tx(1, "S", "X", 500, 0), tx(2, "X", "DEP", 500, 10)])
    assert brief(ws) == [("DEP", D(500), None, "derived", ["tx2"])]
    assert ws[0]["kind"] == "deposit" and ws[0]["label"] == "ExA toy label"


def test_a_direct_payment_and_a_pass_through_into_one_wallet_are_two_rows():
    ws = rows([tx(1, "S", "HOT1", 250, 0), tx(2, "S", "X", 750, 1), tx(3, "X", "HOT1", 750, 9)])
    assert brief(ws) == [("X", D(750), "HOT1", "curated", ["tx2", "tx3"]),
                         ("HOT1", D(250), None, "curated", ["tx1"])]


def test_the_exchanges_own_wallet_and_an_inbound_candidate_have_no_rows():
    tr = trace("HOT1", CHAIN, ToyProvider([tx(1, "HOT1", "A", 5, 0)]), ToyLabels(LABELS),
               TraceConfig())
    own = next(c for c in attribute(tr).candidates if c.hops == 0)
    assert own.request_wallets == []
    tr = trace("S", CHAIN, ToyProvider([tx(1, "HOT1", "S", 50, 0), tx(2, "S", "A", 50, 5)]),
               ToyLabels(LABELS), TraceConfig())
    inbound = next(c for c in attribute(tr).candidates if c.direction == "inbound")
    assert inbound.request_wallets == []
