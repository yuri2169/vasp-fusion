"""The narrative an officer reads and the CaseDetail JSON the UI gets, built from a
trace + attribution. Toy transfers (tracekit.py)."""
from datetime import datetime, timezone

import pytest

from tracekit import CHAIN, ToyLabels, ToyProvider, tx
from vaspfusion.api import schemas as S
from vaspfusion.attribute.rules import RuleConfig, attribute
from vaspfusion.cases import run_case, skeleton
from vaspfusion.explain import fmt
from vaspfusion.explain.case_narrative import narrative
from vaspfusion.trace import TraceConfig, trace

LABELS = {
    "HOT": ("ExA", "exchange", "hot", "curated"),
    "DEP": ("ExC", "exchange", "deposit", "explorer_tag"),
    "POR": ("ExB", "exchange", "reserve", "published_por"),
    "OFAC": ("OFAC SDN", "sanctioned"),
    "SWAP": ("ChangeNOW", "swap_service", "hot", "curated"),
}
SPLIT = [tx(1, "S", "M1", 600, 0), tx(2, "M1", "HOT", 600, 16), tx(3, "S", "POR", 400, 30),
         tx(4, "POR", "S", 1000, -10), tx(5, "S", "ELSE", 7, 40, asset="COIN")]
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def story(transfers, labels=LABELS, **cfg):
    tr = trace("S", CHAIN, ToyProvider(transfers), ToyLabels(labels), TraceConfig(**cfg))
    return narrative(tr, attribute(tr), RuleConfig())


def case(transfers, labels=LABELS, **kw):
    kw.setdefault("case_id", "c-test")
    return run_case("S", "tron", ToyProvider(transfers), ToyLabels(labels), now=NOW, **kw)


# ------------------------------------------------------------------ formatting
@pytest.mark.parametrize("value,text", [("48500", "48,500"), ("252163.80319", "252,163.80"),
                                        ("0.002427667456", "0.002428"), ("1200.000000", "1,200"),
                                        ("53.94", "53.94")])
def test_amounts(value, text):
    assert fmt.amount(value) == text


@pytest.mark.parametrize("share,text", [(1, "100%"), (0.999, "99%"), (0.4615, "46%"),
                                        (0.004, "under 1%"), (0, "0%")])
def test_percentages_never_round_to_all_or_nothing(share, text):
    assert fmt.pct(share) == text


@pytest.mark.parametrize("seconds,text", [(24, "24 seconds"), (960, "16 minutes"),
                                          (3600, "1 hour"), (200000, "2 days")])
def test_durations(seconds, text):
    assert fmt.duration(seconds) == text


def test_long_addresses_are_shortened_in_the_middle():
    assert fmt.short("TVZpWtHzwWsD4f9R5BHDRB3y4yskKjUtzR") == "TVZpWt…KjUtzR"


# ------------------------------------------------------------------ narrative
def test_narrative_of_an_attributed_wallet():
    text = story(SPLIT)
    assert text.startswith("Wallet S sent 1,000 USDT on Toy in 2 transfers")
    assert "400 USDT (40%) reached ExB in 1 hop" in text
    assert "600 USDT (60%) reached ExA in 2 hops within 16 minutes" in text
    assert "published by the exchange itself" in text and "curated list" in text
    assert "Nearest exchange: ExB" in text
    assert "rule-based, not calibrated" in text
    assert "Transaction hashes: tx3" in text


def test_narrative_mentions_who_funded_the_wallet_and_what_was_not_followed():
    text = story(SPLIT)
    assert "100% came directly from ExB" in text
    assert "Not followed in this run: 7 COIN in 1 transfer" in text


def test_narrative_of_an_abstain_names_no_exchange():
    text = story([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "M2", 1000, 5)], max_hops=2)
    assert "No exchange is named." in text
    assert "Nearest exchange" not in text


def test_narrative_of_a_weak_candidate_does_not_present_it_as_the_answer():
    text = story([tx(1, "S", "DEP", 100, 0), tx(2, "S", "X", 900, 1)])
    assert "No exchange is named." in text and "Only 10%" in text


def test_narrative_of_a_sanctioned_reach_leads_with_it():
    text = story([tx(1, "S", "M1", 920, 0), tx(2, "M1", "OFAC", 920, 5), tx(3, "S", "HOT", 80, 6)])
    assert "92% of the funds (920 USDT) reached a sanctioned address" in text
    assert text.index("sanctioned") < text.index("ExA")
    assert "Transaction hashes: tx1, tx2" in text


def test_narrative_of_a_sanctioned_reach_with_no_exchange_says_so():
    text = story([tx(1, "S", "OFAC", 1000, 0)])
    assert "No labelled exchange was reached." in text
    assert "rule confidence" not in text


def test_narrative_gives_the_hop_range_when_money_took_two_routes():
    text = story([tx(1, "S", "POR", 200, 0), tx(2, "S", "M1", 800, 1), tx(3, "M1", "POR", 800, 2)])
    assert "1,000 USDT (100%) reached ExB in 1 to 2 hops, at POR" in text


def test_narrative_of_a_mixer_address_says_what_it_is_once():
    text = story([tx(1, "S", "X", 5, 0)], labels={"S": ("Tornado.Cash", "mixer")})
    assert text.count("labelled Tornado.Cash") == 1
    assert "Nearest exchange" not in text


def test_narrative_of_a_wallet_that_sent_nothing():
    assert "has not sent" in story([tx(1, "X", "S", 5, 0)])


# ------------------------------------------------------------------ CaseDetail
def test_the_case_is_a_valid_case_detail():
    c = case(SPLIT, meta={"case_ref": "FIR 12/2026", "complaint_no": "315", "amount_lost_inr": 5e5})
    S.CaseDetail.model_validate(c)
    assert (c["id"], c["status"], c["outcome"], c["top_vasp"]) == \
        ("c-test", "done", "ATTRIBUTED", "ExB")
    assert c["confidence"] == pytest.approx(0.95)
    assert (c["case_ref"], c["complaint_no"], c["amount_lost_inr"]) == ("FIR 12/2026", "315", 5e5)
    assert c["created_at"] == "2026-10-01T12:00:00Z" and c["demo"] is False
    assert (c["asset"], c["total_sent"], c["total_received"]) == ("USDT", 1000.0, 1000.0)


def test_candidates_are_in_proximity_order_with_both_numbers():
    c = case(SPLIT)
    assert [(x["vasp"], x["proximity_rank"], x["direction"]) for x in c["candidates"]] == \
        [("ExB", 1, "outbound"), ("ExA", 2, "outbound"), ("ExB", 3, "inbound")]
    first = c["candidates"][0]
    assert (first["hops"], first["share_of_funds"], first["label_tier"]) == (1, 0.4, "published_por")
    assert first["confidence_interval"] is None and first["counterfactual"] is None
    assert first["path"] == ["S", "POR"] and first["deposit_address"] == "POR"
    assert c["candidates"][1]["time_to_reach_s"] == 960


def test_graph_roles_and_clusters():
    c = case(SPLIT + [tx(9, "S", "SWAP", 50, 50)])
    nodes = {n["id"]: n for n in c["graph"]["nodes"]}
    assert (nodes["S"]["role"], nodes["S"]["hop"]) == ("suspect", 0)
    assert (nodes["M1"]["role"], nodes["M1"]["hop"], nodes["M1"]["label"]) == ("intermediary", 1, None)
    assert (nodes["HOT"]["role"], nodes["HOT"]["cluster"], nodes["HOT"]["hop"]) == \
        ("exchange_hot", "ExA", 2)
    assert nodes["POR"]["role"] == "exchange" and nodes["POR"]["label"]["tier"] == "published_por"
    assert nodes["SWAP"]["role"] == "swap_service"
    assert len(nodes) == len(c["graph"]["nodes"])      # one node per address, both directions


def test_hub_and_unexpanded_wallets_have_their_own_roles():
    fan = [tx(10 + i, "HUB", f"U{i}", 10, 5 + i) for i in range(6)]
    c = case([tx(1, "S", "HUB", 900, 0), *fan, tx(2, "S", "M1", 100, 1), tx(3, "M1", "END", 100, 2),
              tx(4, "S", "DEP", 500, 3)], cfg=TraceConfig(hub_degree=5, max_hops=2))
    nodes = {n["id"]: n for n in c["graph"]["nodes"]}
    assert (nodes["HUB"]["role"], nodes["HUB"]["is_hub"]) == ("hub", True)
    assert nodes["END"]["role"] == "unknown"
    assert nodes["DEP"]["role"] == "exchange_deposit"


def test_edges_carry_the_transfer_and_the_traced_part():
    c = case([tx(1, "S", "M1", 1000, 0), tx(2, "OTHER", "M1", 4000, 1), tx(3, "M1", "HOT", 5000, 5),
              tx(4, "POR", "S", 1000, -10)])
    edges = {e["tx_hash"]: e for e in c["graph"]["edges"]}
    assert (edges["tx3"]["amount"], edges["tx3"]["traced_amount"], edges["tx3"]["direction"]) == \
        (5000.0, 1000.0, "outbound")
    assert (edges["tx4"]["source"], edges["tx4"]["target"], edges["tx4"]["direction"]) == \
        ("POR", "S", "inbound")
    assert [e["id"] for e in c["graph"]["edges"]] == ["e1", "e2", "e3"]
    assert edges["tx1"]["block_time"] == "2026-01-01T00:00:00Z"


def test_the_hop_rail_follows_the_named_candidate():
    c = case([tx(1, "S", "M1", 1000, 0), tx(2, "M1", "HOT", 1000, 16)])
    rail = c["hop_rail"]
    assert [(h["index"], h["from_address"], h["to_address"], h["elapsed_s"]) for h in rail] == \
        [(1, "S", "M1", None), (2, "M1", "HOT", 960)]
    assert rail[1]["amount"] == 1000.0 and rail[1]["traced_amount"] == 1000.0


def test_an_abstain_case_says_why_and_its_rail_shows_where_most_money_stopped():
    c = case([tx(1, "S", "M1", 900, 0), tx(2, "M1", "M2", 900, 5), tx(3, "S", "X", 100, 6)],
             cfg=TraceConfig(max_hops=2))
    assert (c["outcome"], c["top_vasp"], c["confidence"]) == ("INSUFFICIENT_EVIDENCE", None, None)
    assert c["abstain_reason"] and c["what_would_change"]
    assert [h["to_address"] for h in c["hop_rail"]] == ["M1", "M2"]
    assert "No exchange is named." in c["narrative"]


def test_where_the_funds_went_adds_up():
    fan = [tx(10 + i, "HUB", f"U{i}", 10, 5 + i) for i in range(6)]
    c = case([tx(1, "S", "HUB", 300, 0), *fan, tx(2, "S", "HOT", 500, 1), tx(3, "S", "OFAC", 200, 2)],
             cfg=TraceConfig(hub_degree=5))
    slices = [(s["kind"], s["name"], s["share"]) for s in c["where_funds_went"]]
    assert slices == [("vasp", "ExA", 0.5), ("hub", None, 0.3), ("sanctioned", "OFAC SDN", 0.2)]
    assert sum(s["share"] for s in c["where_funds_went"]) == pytest.approx(1.0)
    assert c["outcome"] == "SANCTIONED_OR_MIXER_REACHED"
    assert c["typology_flags"][0]["code"] == "sanctioned_contact"


def test_provenance_records_the_run():
    c = case(SPLIT, label_db_sha256="ab" * 32)
    p = c["provenance"]
    assert (p["seed"], p["label_db_sha256"]) == (26182, "ab" * 32)
    assert p["code_version"].startswith("b6")


def test_the_same_inputs_give_the_same_case():
    assert case(SPLIT) == case(list(reversed(SPLIT)))


def test_a_skeleton_is_a_valid_empty_case_detail():
    s = skeleton({"id": "c-1", "address": "S", "chain": "tron", "status": "queued",
                  "created_at": "2026-10-01T12:00:00Z"})
    S.CaseDetail.model_validate(s)
    assert s["candidates"] == [] and s["narrative"] == ""


# ------------------------------------------------------------------ model-scored labels (B6)
SCORED = {**LABELS, "MDEP": ("ExA", "exchange", "deposit", "derived", 0.80, "Sweep rule. Model.",
                             0.76, 0.84, '[{"feature": "forward_ratio", "text": "forwards 100% '
                             'of what it receives to one wallet", "weight": 1.9}]')}


def test_a_case_through_a_model_scored_label_carries_the_range_and_says_what_is_calibrated():
    c = case([tx(1, "S", "MDEP", 1000, 0)], labels=SCORED)
    cand = c["candidates"][0]
    assert cand["confidence"] == 0.8 and cand["confidence_interval"] == [0.76, 0.84]
    assert any(e["kind"] == "model" and e["weight"] == 1.9 for e in cand["evidence"])
    assert "Nearest exchange: ExA, confidence 0.80 (range 0.76 to 0.84)." in c["narrative"]
    assert "rule-based, not calibrated" not in c["narrative"]
    node = [n for n in c["graph"]["nodes"] if n["id"] == "MDEP"][0]
    assert node["label"]["reasons"][0]["feature"] == "forward_ratio"
    assert node["label"]["confidence_low"] == 0.76


def test_a_case_through_rule_weighted_labels_still_says_it_is_not_calibrated():
    c = case([tx(1, "S", "HOT", 1000, 0)])
    assert c["candidates"][0]["confidence_interval"] is None
    assert "rule confidence 0.85 (rule-based, not calibrated)" in c["narrative"]
