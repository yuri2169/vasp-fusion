"""The risk score, on the real demo cases (the interface's fixtures). A case with one
more indicator is made by adding a real flag from another real case, never by inventing
a transfer."""
import copy
import json
from pathlib import Path

import pytest

from vaspfusion import risk
from vaspfusion.api import schemas as S

FIXTURES = Path(__file__).resolve().parents[1] / "ui" / "src" / "test" / "fixtures" / "cases"
NAMES = sorted(p.stem for p in FIXTURES.glob("*.json"))
CFG = risk.load_config()


def case(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


CASES = {n: case(n) for n in NAMES}
DONE = {n: c for n, c in CASES.items() if c["status"] == "done" and c.get("outcome")}


def _bare(c: dict) -> dict:
    """The same case with nothing a risk indicator could read."""
    c = copy.deepcopy(c)
    c["typology_flags"] = []
    c["where_funds_went"] = [s for s in c["where_funds_went"] if s["kind"] != "hub"]
    for n in c["graph"]["nodes"]:
        if (n.get("label") or {}).get("category") in ("scam", "swap_service"):
            n["label"] = None
    return c


def _flag(code: str, **over) -> dict:
    return {"code": code, "severity": "warn", "wallet": "W", "text": f"a {code} was seen",
            "figures": {}, "tx_hashes": [], **over}


# ------------------------------------------------------------------ the rules
@pytest.mark.parametrize("name", sorted(DONE))
def test_the_score_is_bounded_and_is_a_valid_risk_block(name):
    r = risk.case_risk(DONE[name])
    assert 0 <= r["score"] <= 100 and r["risk_class"] in risk.CLASSES
    assert r["score"] == min(100, sum(i["points"] for i in r["indicators"]))
    assert len({i["code"] for i in r["indicators"]}) == len(r["indicators"])
    assert r["basis"] == S.RISK_BASIS and "Red Flag Indicators" in r["source"]
    S.RiskInfo.model_validate(r)


@pytest.mark.parametrize("name", sorted(DONE))
def test_the_same_case_always_gives_the_same_score(name):
    again = json.loads(json.dumps(DONE[name]))
    again["typology_flags"] = list(reversed(again["typology_flags"]))
    again["graph"]["nodes"] = list(reversed(again["graph"]["nodes"]))
    a, b = risk.case_risk(DONE[name]), risk.case_risk(again)
    assert (a["score"], a["risk_class"], a["indicators"]) == \
        (b["score"], b["risk_class"], b["indicators"])


@pytest.mark.parametrize("name", sorted(DONE))
def test_the_score_never_goes_down_when_an_indicator_is_added(name):
    c = DONE[name]
    before = risk.case_risk(c)
    for code in risk.PATTERNS + ("bridge_hop", "mixer_contact", "sanctioned_contact"):
        more = {**c, "typology_flags": c["typology_flags"] + [
            _flag(code, figures={"share": 0.5, "hops": 2.0})]}
        after = risk.case_risk(more)
        assert after["score"] >= before["score"], code
        assert risk.RANK[after["risk_class"]] >= risk.RANK[before["risk_class"]], code
    # and taking every flag away never raises it
    assert risk.case_risk({**c, "typology_flags": []})["score"] <= before["score"]


def test_an_indicator_seen_many_times_counts_once():
    base = _bare(DONE["tron-coindcx"])
    one = risk.case_risk({**base, "typology_flags": [_flag("rapid_forwarding", tx_hashes=["a"])]})
    five = risk.case_risk({**base, "typology_flags": [
        _flag("rapid_forwarding", wallet=f"W{i}", tx_hashes=[f"h{i}"]) for i in range(5)]})
    assert one["score"] == five["score"] == CFG["indicators"]["rapid_forwarding"]["points"]
    assert len(five["indicators"]) == 1
    assert five["indicators"][0]["tx_hashes"] == [f"h{i}" for i in range(5)]
    assert "4 more of this kind" in five["indicators"][0]["text"]


def test_the_score_is_capped_at_100():
    base = _bare(DONE["tron-coindcx"])
    flags = [_flag("sanctioned_contact", figures={"share": 1.0, "hops": 1.0}),
             _flag("mixer_contact", figures={"share": 1.0, "hops": 1.0}),
             *[_flag(code) for code in risk.PATTERNS]]
    r = risk.case_risk({**base, "typology_flags": flags})
    assert r["score"] == 100 and r["risk_class"] == "severe"
    assert sum(i["points"] for i in r["indicators"]) > 100


# ------------------------------------------------------------------ each indicator alone
@pytest.mark.parametrize("code", risk.PATTERNS)
def test_each_pattern_alone_adds_exactly_its_points(code):
    base = _bare(DONE["tron-coindcx"])
    assert risk.case_risk(base)["score"] == 0
    r = risk.case_risk({**base, "typology_flags": [_flag(code)]})
    assert [i["code"] for i in r["indicators"]] == [code]
    assert r["score"] == CFG["indicators"][code]["points"]
    assert r["indicators"][0]["fatf_category"] == CFG["indicators"][code]["fatf_category"]


@pytest.mark.parametrize("code,kind", [("sanctioned_contact", "sanctioned"),
                                       ("mixer_contact", "mixer")])
def test_a_sanctioned_or_mixer_contact_is_severe_however_small_or_far(code, kind):
    base = _bare(DONE["tron-coindcx"])
    far = risk.case_risk({**base, "typology_flags": [
        _flag(code, figures={"share": 0.001, "hops": 3.0, "amount": 1.0})]})
    near = risk.case_risk({**base, "typology_flags": [
        _flag(code, figures={"share": 1.0, "hops": 1.0, "amount": 1.0})]})
    ind = CFG["indicators"][f"{kind}_contact"]
    assert far["risk_class"] == near["risk_class"] == "severe"
    assert far["score"] == ind["points"] and near["score"] == ind["points"] + ind["extra"]
    two = risk.case_risk({**base, "typology_flags": [
        _flag(code, figures={"share": 1.0, "hops": 2.0, "amount": 1.0})]})
    assert far["score"] < two["score"] < near["score"]      # weighted by share and distance


def test_the_wallet_itself_being_listed_is_its_own_indicator():
    base = _bare(DONE["tron-coindcx"])
    r = risk.case_risk({**base, "typology_flags": [
        _flag("sanctioned_contact", wallet=base["address"], severity="high")]})
    assert [i["code"] for i in r["indicators"]] == ["sanctioned_self"] and r["score"] == 100


def test_being_funded_by_a_sanctioned_address_counts_less_than_paying_one():
    base = _bare(DONE["tron-coindcx"])
    funder = next(e["source"] for e in base["graph"]["edges"] if e["direction"] == "inbound")
    r = risk.case_risk({**base, "typology_flags": [
        _flag("sanctioned_contact", wallet=funder, figures={"share": 1.0, "hops": 1.0})]})
    assert [i["code"] for i in r["indicators"]] == ["sanctioned_funding"]
    assert r["risk_class"] == "high"


def test_a_bridge_counts_by_the_share_that_went_into_it():
    base = _bare(DONE["tron-coindcx"])
    small = risk.case_risk({**base, "typology_flags": [
        _flag("bridge_hop", figures={"share": 0.04, "hops": 3.0})]})
    large = risk.case_risk({**base, "typology_flags": [
        _flag("bridge_hop", figures={"share": 1.0, "hops": 1.0})]})
    assert small["score"] == 15 and large["score"] == 30
    assert (small["risk_class"], large["risk_class"]) == ("low", "medium")


def test_a_scam_label_and_a_swap_service_on_the_trail_are_indicators():
    base = _bare(DONE["tron-coindcx"])
    paid = next(e for e in base["graph"]["edges"] if e["direction"] == "outbound")
    for cat, code in (("scam", "scam_contact"), ("swap_service", "swap_service")):
        c = copy.deepcopy(base)
        node = next(n for n in c["graph"]["nodes"] if n["id"] == paid["target"])
        node["label"] = {**(node["label"] or {}), "category": cat, "entity": "X",
                         "label": "X", "source": "a-list"}
        r = risk.case_risk(c)
        assert [i["code"] for i in r["indicators"]] == [code]
        assert paid["tx_hash"] in r["indicators"][0]["tx_hashes"]


def test_most_funds_stopping_at_an_unlabelled_busy_wallet_is_an_indicator():
    c = DONE["tron-abstain"]
    hub = sum(s["share"] for s in c["where_funds_went"] if s["kind"] == "hub")
    assert hub >= 0.5
    assert "unlabelled_hub" in [i["code"] for i in risk.case_risk(c)["indicators"]]
    under = {**c, "where_funds_went": [{**s, "share": 0.49} if s["kind"] == "hub" else s
                                       for s in c["where_funds_went"]]}
    assert "unlabelled_hub" not in [i["code"] for i in risk.case_risk(under)["indicators"]]


def test_a_lead_from_the_deposit_model_is_not_a_risk():
    base = _bare(DONE["tron-coindcx"])
    assert risk.case_risk({**base, "typology_flags": [_flag("deposit_like")]})["score"] == 0


# ------------------------------------------------------------------ the recorded cases
def test_the_ofac_case_is_severe_and_a_clean_attributed_case_is_not():
    ofac = risk.case_risk(DONE["tron-ofac"])
    assert ofac["risk_class"] == "severe" and ofac["score"] == 100
    assert ofac["indicators"][0]["code"] == "sanctioned_contact"
    assert ofac["indicators"][0]["tx_hashes"]
    for name in ("tron-coindcx", "tron-htx-coindcx"):
        clean = risk.case_risk(DONE[name])
        assert DONE[name]["outcome"] == "ATTRIBUTED"
        assert clean["risk_class"] == "low", name


def test_a_case_with_no_result_has_no_risk():
    c = DONE["tron-coindcx"]
    assert risk.case_risk({**c, "status": "running"}) is None
    assert risk.summary({**c, "status": "failed"}) == {"risk_class": None, "risk_score": None}
    assert risk.summary(None) == {"risk_class": None, "risk_score": None}


# ------------------------------------------------------------------ flows
def test_the_transfer_into_the_sanctioned_address_is_severe_and_the_path_with_it():
    c = DONE["tron-ofac"]
    r = risk.case_risk(c)
    listed = next(n["id"] for n in c["graph"]["nodes"] if n["role"] == "sanctioned")
    into = [e["id"] for e in c["graph"]["edges"]
            if e["target"] == listed and e["direction"] == "outbound"]
    by_edge = {f["edge_id"]: f for f in r["flows"]}
    assert into and all(by_edge[i]["risk_class"] == "severe" for i in into)
    assert by_edge[into[0]]["reasons"][0] == "Funds reached a sanctioned address"
    assert r["path_class"] == "severe"
    assert all(f["risk_class"] != "low" for f in r["flows"])


def test_a_path_through_a_mixer_is_severe_even_if_the_wallet_is_otherwise_quiet():
    base = _bare(DONE["tron-coindcx"])
    hop = base["hop_rail"][0]
    r = risk.case_risk({**base, "typology_flags": [
        _flag("mixer_contact", severity="high", wallet=hop["to_address"],
              figures={"share": 0.01, "hops": 1.0}, tx_hashes=[hop["tx_hash"]])]})
    assert r["path_class"] == "severe"
    assert [f["risk_class"] for f in r["flows"] if f["tx_hash"] == hop["tx_hash"]] == ["severe"]


def test_a_quiet_case_has_no_flows_above_low():
    r = risk.case_risk(_bare(DONE["tron-coindcx"]))
    assert r["flows"] == [] and r["path_class"] == "low"


# ------------------------------------------------------------------ wallets
def test_a_wallet_in_no_case_and_unlabelled_is_not_assessed():
    r = risk.wallet_risk("T" + "X" * 33, None, [])
    assert r["score"] is None and r["risk_class"] is None and r["indicators"] == []


def test_a_listed_address_is_severe_by_its_label():
    c = DONE["tron-ofac"]
    node = next(n for n in c["graph"]["nodes"] if n["role"] == "sanctioned")
    r = risk.wallet_risk(node["id"], node["label"], [c])
    assert r["risk_class"] == "severe" and r["indicators"][0]["code"] == "sanctioned_self"
    assert "sanctions list" in r["reasons"][0] and "ofac-sdn" in r["reasons"][0]


def test_the_traced_wallet_carries_its_cases_indicators():
    c = DONE["tron-ofac"]
    r = risk.wallet_risk(c["address"], None, [c])
    assert r["risk_class"] == "severe"
    assert r["indicators"][0]["case_id"] == c["id"]
    assert r["reasons"][0].startswith(f"Case {c['case_ref'] or c['id']}: ")


def test_a_wallet_on_someone_elses_trail_carries_only_what_was_seen_of_it():
    c = DONE["tron-ofac"]
    passer = next(f["wallet"] for f in c["typology_flags"] if f["code"] == "rapid_forwarding")
    r = risk.wallet_risk(passer, None, [c])
    assert [i["code"] for i in r["indicators"]] == ["rapid_forwarding"]
    bystander = next(n["id"] for n in c["graph"]["nodes"]
                     if n["role"] == "unknown" and n["id"] != passer)
    quiet = risk.wallet_risk(bystander, None, [c])
    assert quiet["score"] == 0 and quiet["risk_class"] == "low"


# ------------------------------------------------------------------ the config
def test_the_config_is_refused_when_it_breaks_its_rules(tmp_path):
    import yaml
    good = yaml.safe_load(risk.DEFAULT_PATH.read_text())

    def refused(change, words):
        doc = copy.deepcopy(good)
        change(doc)
        path = tmp_path / f"{abs(hash(words))}.yaml"
        path.write_text(yaml.safe_dump(doc, sort_keys=False))
        with pytest.raises(risk.RiskConfigError, match=words):
            risk.load_config(path)

    refused(lambda d: d["classes"].update(medium=80), "classes must be")
    refused(lambda d: d["indicators"].pop("peel_chain"), "indicators missing: peel_chain")
    refused(lambda d: d["indicators"]["fan_in"].update(points=-1), "fan_in.points")
    refused(lambda d: d["indicators"]["fan_in"].pop("fatf_category"), "fatf_category")
    refused(lambda d: d.pop("source"), "source needs")


def test_the_classes_are_read_off_the_score():
    assert [risk.class_of(s) for s in (0, 24, 25, 49, 50, 74, 75, 100)] == \
        ["low", "low", "medium", "medium", "high", "high", "severe", "severe"]


# ------------------------------------------------------------------ threat tags
TAG = {"threat": "ransomware", "entity": "Conti", "source": "ransomwhere", "url": None,
       "evidence": "Ransomwhere: ransomware payment address, family Conti."}


def test_a_link_to_a_threat_tagged_address_is_severe_and_counted_once():
    base = _bare(DONE["tron-coindcx"])
    paid = next(e for e in base["graph"]["edges"] if e["direction"] == "outbound")
    flag = _flag("threat_contact", severity="high", wallet=paid["target"], threat=TAG,
                 figures={"share": 0.14, "hops": 2.0}, tx_hashes=[paid["tx_hash"]],
                 text="Linked to ransomware (Conti, Ransomwhere): 2 hops away")
    r = risk.case_risk({**base, "typology_flags": [flag]})
    assert [i["code"] for i in r["indicators"]] == ["threat_contact"]
    assert r["risk_class"] == "severe" and r["indicators"][0]["text"] == flag["text"]
    # a scam-listed wallet that carries a tag is that same link, not a second indicator
    c = copy.deepcopy(base)
    node = next(n for n in c["graph"]["nodes"] if n["id"] == paid["target"])
    node["label"] = {**(node["label"] or {}), "category": "scam", "entity": "X", "label": "X",
                     "source": "a-list", "threat": "fraud", "threat_entity": "X",
                     "threat_source": "a-list"}
    both = risk.case_risk({**c, "typology_flags": [flag]})
    assert [i["code"] for i in both["indicators"]] == ["threat_contact"]


def test_a_tagged_address_is_severe_by_its_tag_in_the_sources_words():
    label = {"category": "entity", "entity": "Conti", "source": "ransomwhere", "label": "Conti",
             "threat": "ransomware", "threat_entity": "Conti", "threat_source": "ransomwhere",
             "threat_url": None, "threat_evidence": TAG["evidence"]}
    r = risk.wallet_risk("RW", label, [])
    assert (r["risk_class"], r["indicators"][0]["code"]) == ("severe", "threat_self")
    assert r["reasons"][0].endswith(TAG["evidence"])


# ------------------------------------------------------------------ the pattern cap (E2)
def test_the_pattern_rules_together_never_lift_a_wallet_out_of_low():
    cfg = risk.load_config()
    every = {c: cfg["indicators"][c]["points"] for c in risk.CAPPED}
    assert sum(every.values()) > cfg["pattern_cap"]
    assert risk.total(every, cfg) == cfg["pattern_cap"] < cfg["classes"]["medium"]
    assert risk.class_of(risk.total(every, cfg), cfg) == "low"


def test_the_cap_leaves_every_other_indicator_whole_and_never_lowers_a_score():
    cfg = risk.load_config()
    every = {c: cfg["indicators"][c]["points"] for c in risk.CAPPED}
    hub = {"unlabelled_hub": cfg["indicators"]["unlabelled_hub"]["points"]}
    assert risk.total({**every, **hub}, cfg) == cfg["pattern_cap"] + hub["unlabelled_hub"]
    assert risk.total({"mixer_contact": 75, **every}, cfg) == 95
    grown: dict = {}
    for code, pts in {**every, **hub, "bridge_hop": 15}.items():
        before = risk.total(grown, cfg)
        grown[code] = pts
        assert risk.total(grown, cfg) >= before


def test_a_config_with_no_cap_adds_the_patterns_in_full():
    cfg = {**risk.load_config(), "pattern_cap": None}
    every = {c: cfg["indicators"][c]["points"] for c in risk.CAPPED}
    assert risk.total(every, cfg) == sum(every.values())
