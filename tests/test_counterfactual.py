"""Counterfactual: hide the label a named exchange was entered at, trace again, compare."""
from tracekit import CHAIN, ToyLabels, ToyProvider, tx
from vaspfusion.attribute.counterfactual import HiddenLabels, add_counterfactuals
from vaspfusion.attribute.rules import RuleConfig, attribute
from vaspfusion.trace import TraceConfig, trace

LABELS = {"DEP": ("ExA", "exchange", "deposit", "explorer_tag"),
          "HOT": ("ExA", "exchange", "hot", "curated"),
          "TAG": ("ExB", "exchange", "deposit", "explorer_tag"),
          "OFAC": ("OFAC SDN", "sanctioned")}


def case(transfers, labels=LABELS, rules=RuleConfig(), fail=(), **cfg):
    labels, cfg = ToyLabels(labels), TraceConfig(**cfg)
    provider = ToyProvider(transfers)
    tr = trace("S", CHAIN, provider, labels, cfg)
    att = attribute(tr, rules)
    before = (att.outcome, [(c.vasp, c.confidence, c.proximity_rank) for c in att.candidates])
    provider.fail = set(fail)
    add_counterfactuals(tr, att, provider, labels, cfg, rules)
    assert before == (att.outcome, [(c.vasp, c.confidence, c.proximity_rank)
                                    for c in att.candidates])
    assert att.top is None or att.top is att.candidates[[c.vasp for c in att.candidates]
                                                         .index(att.top.vasp)]
    return att


def test_the_answer_holds_when_the_exchange_wallet_behind_the_deposit_address_is_labelled():
    att = case([tx(1, "S", "DEP", 1000, 0), tx(2, "DEP", "HOT", 1000, 5)])
    c = att.top
    assert c.vasp == "ExA" and c.hops == 1 and c.counterfactual_holds is True
    # explorer tag at 1 hop = 0.75; without it the curated hot wallet at 2 hops = 0.85 x 0.85
    assert c.counterfactual == ("Still ExA without the label on DEP: 100% of the funds reach "
                                "ExA at HOT (curated list) in 2 hops, confidence 0.72 "
                                "(was 0.75).")
    item = c.evidence[-1]
    assert item == {"kind": "counterfactual", "tier": None, "text": c.counterfactual,
                    "tx_hashes": ["tx1", "tx2"], "weight": -0.0275}


def test_an_answer_that_rests_on_one_label_says_so():
    att = case([tx(1, "S", "TAG", 1000, 0)])
    c = att.top
    assert c.counterfactual_holds is False
    assert c.counterfactual == ("Without the label on TAG, ExB is not reached at all: naming "
                                "ExB rests on that one label.")
    assert c.evidence[-1]["weight"] == -0.75 and c.evidence[-1]["tx_hashes"] == []


def test_still_reached_but_under_the_bar_is_weaker_not_holding():
    # behind the tagged deposit address the money takes two more hops to the hot wallet
    rows = [tx(1, "S", "DEP", 1000, 0), tx(2, "DEP", "M", 1000, 5), tx(3, "M", "HOT", 1000, 9)]
    att = case(rows, rules=RuleConfig(attribute_min=0.7))
    c = att.top
    assert c.counterfactual_holds is False
    assert c.counterfactual == ("Without the label on DEP, 100% of the funds reach ExA at HOT "
                                "(curated list) in 3 hops, but confidence falls to 0.61, below "
                                "the 0.70 needed to name an exchange (was 0.75).")


def test_every_named_candidate_is_checked_and_unnamed_ones_are_not():
    rows = [tx(1, "S", "DEP", 500, 0), tx(2, "DEP", "HOT", 500, 5), tx(3, "S", "TAG", 450, 1),
            tx(4, "S", "M", 50, 2), tx(5, "M", "M2", 50, 3)]
    att = case(rows)
    by = {c.vasp: c for c in att.candidates}
    assert by["ExA"].counterfactual_holds is True and by["ExB"].counterfactual_holds is False
    weak = case([tx(1, "S", "TAG", 50, 0), tx(2, "S", "X", 950, 1)])
    assert weak.outcome == "INSUFFICIENT_EVIDENCE"
    assert weak.candidates[0].counterfactual is None
    assert weak.candidates[0].counterfactual_holds is None
    assert [e["kind"] for e in weak.candidates[0].evidence] == ["label", "path"]


def test_the_wallet_itself_being_an_exchange_address_and_inbound_candidates_are_not_checked():
    att = case([tx(1, "HOT", "S", 1000, 0), tx(2, "S", "TAG", 1000, 5)])
    by = {(c.vasp, c.direction): c for c in att.candidates}
    assert by[("ExA", "inbound")].counterfactual is None
    assert by[("ExB", "outbound")].counterfactual is not None


def test_hidden_labels_hide_only_what_they_are_told_to():
    hidden = HiddenLabels(ToyLabels(LABELS), {"DEP"})
    assert set(hidden.lookup_many([("DEP", CHAIN), ("HOT", CHAIN), ("X", CHAIN)])) == {("HOT", CHAIN)}


def test_a_second_trace_that_cannot_run_leaves_the_candidate_as_it_was():
    att = case([tx(1, "S", "TAG", 1000, 0)], fail={"S"})
    assert att.top.counterfactual is None and att.top.counterfactual_holds is None
