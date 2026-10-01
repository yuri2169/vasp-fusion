"""Rule attribution: labelled wallets the trace reached -> ranked candidates, a rule
confidence, an outcome. Toy transfers (tracekit.py); real wallets are in test_demo_cases.py."""
from decimal import Decimal as D

import pytest

from tracekit import CHAIN, ToyLabels, ToyProvider, tx
from vaspfusion.attribute.rules import TIER_WEIGHT, RuleConfig, attribute
from vaspfusion.trace import TraceConfig, trace

def approx(x):
    return pytest.approx(x, abs=1e-4)      # confidence is reported to 4 decimals


LABELS = {
    "HOT": ("ExA", "exchange", "hot", "curated"),
    "HOT2": ("ExA", "exchange", "hot", "curated"),
    "POR": ("ExB", "exchange", "reserve", "published_por"),
    "TAG": ("ExC", "exchange", "deposit", "explorer_tag"),
    "ANON": ("Unidentified exchange", "exchange", "unknown", "explorer_tag"),
    "OFAC": ("OFAC SDN", "sanctioned"),
    "MIX": ("Tornado.Cash", "mixer"),
    "BRIDGE": ("Stargate", "bridge"),
}


def run(transfers, labels=LABELS, rules=RuleConfig(), **cfg):
    tr = trace("S", CHAIN, ToyProvider(transfers), ToyLabels(labels), TraceConfig(**cfg))
    return attribute(tr, rules)


def by_vasp(att):
    return {c.vasp: c for c in att.candidates}


# ------------------------------------------------------------------ confidence
def test_one_hop_full_share_is_the_tier_weight():
    att = run([tx(1, "S", "HOT", 1000, 0)])
    c = att.candidates[0]
    assert (c.vasp, c.hops, c.share, c.deposit_address) == ("ExA", 1, D(1), "HOT")
    assert c.confidence == approx(TIER_WEIGHT["curated"])
    assert c.label_tier == "curated" and c.direction == "outbound"


@pytest.mark.parametrize("entry,tier", [("POR", "published_por"), ("HOT", "curated"),
                                        ("TAG", "explorer_tag")])
def test_each_hop_decays_the_tier_weight(entry, tier):
    att = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "M2", 1000, 1), tx(3, "M2", entry, 1000, 2)])
    c = att.candidates[0]
    assert c.hops == 3
    assert c.confidence == approx(TIER_WEIGHT[tier] * 0.85 ** 2)


def test_a_stronger_label_tier_gives_more_confidence():
    assert TIER_WEIGHT["published_por"] > TIER_WEIGHT["curated"] > TIER_WEIGHT["explorer_tag"] \
        > TIER_WEIGHT["derived"]


def test_a_share_of_a_quarter_or_more_counts_in_full():
    att = run([tx(1, "S", "HOT", 460, 0), tx(2, "S", "POR", 540, 1)])
    c = by_vasp(att)
    assert c["ExA"].share == D("0.46") and c["ExB"].share == D("0.54")
    assert c["ExA"].confidence == approx(TIER_WEIGHT["curated"])
    assert c["ExB"].confidence == approx(TIER_WEIGHT["published_por"])


def test_a_small_share_scales_confidence_down():
    att = run([tx(1, "S", "HOT", 100, 0), tx(2, "S", "X", 900, 1)])
    assert att.candidates[0].confidence == approx(TIER_WEIGHT["curated"] * 0.10 / 0.25)


def test_share_full_of_one_is_the_plain_product():
    """tier weight x share x hop decay, exactly as the phase brief writes it."""
    att = run([tx(1, "S", "M1", 460, 0), tx(2, "M1", "HOT", 460, 1), tx(3, "S", "X", 540, 2)],
              rules=RuleConfig(share_full=1.0))
    assert att.candidates[0].confidence == approx(TIER_WEIGHT["curated"] * 0.46 * 0.85)


def test_money_arriving_by_two_routes_is_weighted_by_amount():
    # 200 reach POR in 1 hop, 800 in 2 hops
    att = run([tx(1, "S", "POR", 200, 0), tx(2, "S", "M1", 800, 1), tx(3, "M1", "POR", 800, 2)])
    c = att.candidates[0]
    assert (c.hops, c.hops_max, c.share) == (1, 2, D(1))  # nearest route gives the hop count
    path = next(e for e in c.evidence if e["kind"] == "path")
    assert "in 1 to 2 hops" in path["text"] and "within" not in path["text"]
    assert c.confidence == approx(TIER_WEIGHT["published_por"] * (0.2 + 0.8 * 0.85))


def test_two_wallets_of_one_vasp_are_one_candidate():
    att = run([tx(1, "S", "HOT", 300, 0), tx(2, "S", "HOT2", 700, 1)])
    assert len(att.candidates) == 1
    c = att.candidates[0]
    assert (c.vasp, c.share, c.deposit_address) == ("ExA", D(1), "HOT2")   # the larger entry
    assert sorted(e.address for e in c.entries) == ["HOT", "HOT2"]


def test_confidence_never_exceeds_one():
    assert all(0 <= c.confidence <= 1 for c in run([tx(1, "S", "POR", 5, 0)]).candidates)


def test_a_candidates_hops_path_entry_and_time_describe_one_route():
    # ExA got 10 directly at HOT and 90 at HOT2 by a 3-hop route: the entry that took the
    # most is the one described, and every field describes that same route
    att = run([tx(1, "S", "HOT", 10, 0), tx(2, "S", "M1", 90, 1), tx(3, "M1", "M2", 90, 2),
               tx(4, "M2", "HOT2", 90, 300)])
    c = att.candidates[0]
    assert c.deposit_address == "HOT2" and c.path == ["S", "M1", "M2", "HOT2"]
    assert c.hops == len(c.path) - 1 == 3
    assert (c.hops_min, c.hops_max) == (1, 3)
    assert c.time_to_reach_s == 299 * 60 and c.last_hop == "M2"
    path = next(e for e in c.evidence if e["kind"] == "path")
    assert "in 1 to 3 hops" in path["text"] and path["tx_hashes"] == ["tx2", "tx3", "tx4"]


def test_the_time_to_reach_is_never_negative():
    # the first deposit was swept on; a larger later one was not
    att = run([tx(1, "S", "D", 1000, 1), tx(2, "D", "HOT", 1000, 2), tx(3, "S", "D", 2000, 10)])
    c = att.candidates[0]
    assert [e.transfer.tx_hash for e in c.path_edges] == ["tx1", "tx2"]
    assert c.time_to_reach_s == 60


def test_unnamed_exchange_wallets_are_not_added_together():
    labels = {**LABELS, "ANON2": ("Unidentified exchange", "exchange", "unknown", "explorer_tag")}
    att = run([tx(1, "S", "ANON", 150, 0), tx(2, "S", "ANON2", 150, 1), tx(3, "S", "X", 700, 2)],
              labels=labels)
    assert [(c.vasp, c.deposit_address, c.share) for c in att.candidates] == \
        [("Unidentified exchange", "ANON", D("0.15")), ("Unidentified exchange", "ANON2", D("0.15"))]
    # 15% each stays under the bar; added together (30%) they would have been "named"
    assert att.outcome == "INSUFFICIENT_EVIDENCE"


# ------------------------------------------------------------------ proximity
def test_proximity_is_hops_then_share_then_time():
    att = run([tx(1, "S", "M1", 900, 0), tx(2, "M1", "POR", 900, 5),      # ExB: 2 hops, 90%
               tx(3, "S", "TAG", 100, 1)])                                 # ExC: 1 hop, 10%
    assert [(c.vasp, c.proximity_rank) for c in att.candidates] == [("ExC", 1), ("ExB", 2)]


def test_proximity_and_confidence_can_disagree_and_both_are_reported():
    att = run([tx(1, "S", "M1", 900, 0), tx(2, "M1", "POR", 900, 5), tx(3, "S", "TAG", 100, 1)])
    near, far = att.candidates
    assert near.proximity_rank < far.proximity_rank
    assert near.confidence < far.confidence
    # the nearest candidate does not clear the bar, so the next nearest that does is named
    assert (att.outcome, att.top.vasp) == ("ATTRIBUTED", "ExB")


def test_equal_hops_rank_by_share():
    att = run([tx(1, "S", "HOT", 400, 0), tx(2, "S", "POR", 600, 1)])
    assert [c.vasp for c in att.candidates] == ["ExB", "ExA"]


def test_time_to_reach_is_first_to_last_transfer_on_the_path():
    att = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "HOT", 1000, 16)])
    c = att.candidates[0]
    assert c.time_to_reach_s == 16 * 60
    assert c.path == ["S", "M1", "HOT"] and c.last_hop == "M1"
    assert [e.transfer.tx_hash for e in c.path_edges] == ["tx1", "tx2"]


# ------------------------------------------------------------------ outcomes
def test_attributed_names_the_nearest_candidate_that_clears_the_bar():
    att = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "HOT", 1000, 5)])
    assert (att.outcome, att.top.vasp) == ("ATTRIBUTED", "ExA")
    assert att.abstain_reason is None and att.what_would_change == []
    assert any("ExA" in s for s in att.next_steps)


def test_nothing_labelled_reached_is_insufficient_evidence():
    att = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "M2", 1000, 5)], max_hops=2)
    assert (att.outcome, att.top, att.candidates) == ("INSUFFICIENT_EVIDENCE", None, [])
    assert "labelled" in att.abstain_reason and "2 hops" in att.abstain_reason
    assert any("deeper" in w for w in att.what_would_change)


def test_a_weak_candidate_is_listed_but_not_named():
    att = run([tx(1, "S", "TAG", 100, 0), tx(2, "S", "X", 900, 1)])
    assert att.outcome == "INSUFFICIENT_EVIDENCE" and att.top is None
    assert att.candidates[0].vasp == "ExC"
    assert "10%" in att.abstain_reason and "0.60" in att.abstain_reason
    assert "ExC" in att.abstain_reason


def test_abstain_says_where_the_money_stopped():
    fan = [tx(10 + i, "HUB", f"U{i}", 10, 5 + i) for i in range(6)]
    att = run([tx(1, "S", "HUB", 1000, 0), *fan], hub_degree=5)
    assert att.outcome == "INSUFFICIENT_EVIDENCE"
    assert "high-activity" in att.abstain_reason
    assert any("HUB" in w for w in att.what_would_change)


def test_what_would_change_names_the_wallet_at_the_hop_limit_even_if_it_was_expanded():
    att = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "M2", 1000, 1), tx(3, "M2", "M1", 1000, 2)],
              max_hops=3)
    assert att.outcome == "INSUFFICIENT_EVIDENCE"
    assert "Tracing deeper than 3 hops from M1 (100% of the funds)" in att.what_would_change
    assert "Tracing deeper" not in att.what_would_change       # no vaguer duplicate


def test_abstain_next_steps_are_actions_not_a_repeat_of_what_would_change():
    fan = [tx(10 + i, "HUB", f"U{i}", 10, 5 + i) for i in range(6)]
    att = run([tx(1, "S", "HUB", 900, 0), *fan, tx(2, "S", "TAG", 100, 1)], hub_degree=5)
    assert att.outcome == "INSUFFICIENT_EVIDENCE"
    assert not set(att.next_steps) & set(att.what_would_change)
    assert any("HUB" in s and "Identify" in s for s in att.next_steps)
    assert any("ExC" in s and "10%" in s for s in att.next_steps)


def test_a_wallet_that_sent_nothing_abstains_with_that_reason():
    att = run([tx(1, "X", "S", 100, 0)])
    assert att.outcome == "INSUFFICIENT_EVIDENCE"
    assert "has not sent" in att.abstain_reason


@pytest.mark.parametrize("target,code", [("OFAC", "sanctioned_contact"), ("MIX", "mixer_contact")])
def test_reaching_a_sanctioned_or_mixer_address_is_its_own_outcome(target, code):
    att = run([tx(1, "S", "M1", 920, 0), tx(2, "M1", target, 920, 5), tx(3, "S", "HOT", 80, 6)])
    assert att.outcome == "SANCTIONED_OR_MIXER_REACHED"
    flag = next(f for f in att.flags if f["code"] == code)
    assert (flag["severity"], flag["wallet"]) == ("high", target)
    assert flag["figures"]["share"] == approx(0.92)
    assert flag["tx_hashes"] == ["tx2"]
    assert att.candidates[0].vasp == "ExA"          # the exchange is still listed
    assert att.top is None                          # 8% does not clear the bar
    assert any("scalat" in s for s in att.next_steps)


def test_a_trace_of_sanctioned_funds_keeps_a_strong_candidate_as_top():
    att = run([tx(1, "S", "OFAC", 500, 0), tx(2, "S", "HOT", 500, 1)])
    assert att.outcome == "SANCTIONED_OR_MIXER_REACHED" and att.top.vasp == "ExA"


def test_a_sliver_to_a_sanctioned_address_does_not_change_the_outcome():
    att = run([tx(1, "S", "OFAC", 5, 0), tx(2, "S", "HOT", 995, 1)])
    assert att.outcome == "ATTRIBUTED"
    assert any(f["code"] == "sanctioned_contact" for f in att.flags)    # still flagged


def test_a_bridge_is_flagged():
    att = run([tx(1, "S", "BRIDGE", 1000, 0)])
    flag = att.flags[0]
    assert (flag["code"], flag["severity"], flag["wallet"]) == ("bridge_hop", "warn", "BRIDGE")
    assert att.outcome == "INSUFFICIENT_EVIDENCE" and "bridge" in att.abstain_reason


def test_an_unnamed_exchange_is_a_candidate_that_cannot_be_routed():
    att = run([tx(1, "S", "ANON", 1000, 0)])
    assert att.candidates[0].vasp == "Unidentified exchange"
    assert att.outcome == "ATTRIBUTED"
    assert any("no request can be routed" in s for s in att.next_steps)


def test_a_wallet_that_is_itself_an_exchange_address():
    att = run([tx(1, "S", "X", 1000, 0)], labels={"S": ("ExC", "exchange", "deposit",
                                                        "explorer_tag")})
    c = att.candidates[0]
    assert (att.outcome, c.vasp, c.hops, c.share, c.path) == ("ATTRIBUTED", "ExC", 0, D(1), ["S"])
    assert c.confidence == approx(TIER_WEIGHT["explorer_tag"])


def test_a_sanctioned_wallet_is_flagged_and_still_attributed_forward():
    att = run([tx(1, "S", "HOT", 1000, 0)], labels={**LABELS, "S": ("OFAC SDN", "sanctioned")})
    assert att.outcome == "SANCTIONED_OR_MIXER_REACHED" and att.top.vasp == "ExA"
    assert att.flags[0]["wallet"] == "S"


def test_the_request_names_the_deposit_wallet_only_when_it_passed_everything_on():
    swept = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "HOT", 1000, 1)])
    assert "account behind M1" in swept.next_steps[0]
    # MULE kept half for someone else: it is not the exchange's wallet
    partial = run([tx(1, "S", "MULE", 100, 0), tx(2, "MULE", "HOT", 50, 1),
                   tx(3, "MULE", "OTHER", 50, 2)])
    assert "account behind HOT" in partial.next_steps[0]
    assert "MULE" not in partial.next_steps[0]


def test_a_labelled_deposit_address_is_itself_the_account():
    att = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "TAG", 1000, 1)])
    assert "account behind TAG" in att.next_steps[0]


def test_an_exchange_wallet_as_the_subject_is_not_asked_to_freeze_itself():
    att = run([tx(1, "S", "X", 1000, 0)], labels={"S": ("ExC", "exchange", "hot", "curated")})
    assert not any("freeze" in s for s in att.next_steps)
    assert any("ExC" in s and "own wallet" in s for s in att.next_steps)


# ------------------------------------------------------------------ inbound
def test_an_exchange_that_funded_the_wallet_is_an_inbound_candidate():
    att = run([tx(1, "POR", "S", 1000, 0), tx(2, "S", "M1", 1000, 5), tx(3, "M1", "HOT", 1000, 6)])
    out, inn = att.candidates
    assert (out.vasp, out.direction, out.proximity_rank) == ("ExA", "outbound", 1)
    assert (inn.vasp, inn.direction, inn.proximity_rank, inn.share) == ("ExB", "inbound", 2, D(1))
    assert inn.path == ["POR", "S"]
    assert any("ExB" in s and "funded" in s for s in att.next_steps)


def test_an_inbound_exchange_alone_does_not_attribute():
    att = run([tx(1, "POR", "S", 1000, 0)])
    assert att.outcome == "INSUFFICIENT_EVIDENCE" and att.top is None
    assert att.candidates[0].direction == "inbound"


def test_funding_from_a_sanctioned_address_is_flagged_not_an_outcome():
    att = run([tx(1, "OFAC", "S", 1000, 0), tx(2, "S", "HOT", 1000, 5)])
    assert att.outcome == "ATTRIBUTED"
    flag = next(f for f in att.flags if f["code"] == "sanctioned_contact")
    assert "funded" in flag["text"]


# ------------------------------------------------------------------ evidence
def test_evidence_states_the_label_and_the_path():
    att = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "HOT", 1000, 16)])
    label, path = att.candidates[0].evidence[:2]
    assert (label["kind"], label["tier"]) == ("label", "curated")
    assert "ExA" in label["text"] and "curated list" in label["text"]
    assert label["weight"] == approx(TIER_WEIGHT["curated"])
    assert path["kind"] == "path" and path["tx_hashes"] == ["tx1", "tx2"]
    assert "100%" in path["text"] and "2 hops" in path["text"] and "16 minutes" in path["text"]


def test_evidence_notes_a_last_hop_that_passed_everything_on():
    att = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "HOT", 1000, 1)])
    texts = [e["text"] for e in att.candidates[0].evidence]
    assert any("M1" in t and "passed on all" in t and "within 1 minute" in t for t in texts)
    assert att.candidates[0].passed_all is True
    partial = run([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "HOT", 500, 1), tx(3, "M1", "X", 500, 2)])
    assert not any("passed on all" in e["text"] for e in partial.candidates[0].evidence)
