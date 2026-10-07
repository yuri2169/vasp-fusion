"""The risk validation: hiding labels, the slim case, and the arithmetic of the tables."""
import json
from pathlib import Path

import pytest

from vaspfusion import risk as R
from vaspfusion.eval import risk_validation as V
from vaspfusion.labels.lookup import Label

from demokit import SPECS, run_demo

ROOT = Path(__file__).resolve().parents[1]


def _label(address, entity, **kw):
    return Label(address=address, chain="ethereum", entity=entity, category="sanctioned",
                 kind="unknown", tier="curated", source="s", source_url=None, label=entity, **kw)


class Store:
    def __init__(self, *labels):
        self.rows = {(lab.address, lab.chain): lab for lab in labels}

    def lookup_many(self, pairs):
        return {p: self.rows[p] for p in pairs if p in self.rows}


def test_the_own_label_is_hidden_whatever_the_case_of_the_address():
    store = Store(_label("0xab", "A"), _label("0xcd", "A"))
    seen = V.HiddenLabels(store, "0xAB").lookup_many([("0xab", "ethereum"), ("0xcd", "ethereum")])
    assert list(seen) == [("0xcd", "ethereum")]


def test_every_label_of_the_entity_is_hidden_and_others_stay():
    store = Store(_label("0xab", "A"), _label("0xcd", "A"), _label("0xef", "B"),
                  _label("0x12", "C", threat="fraud", threat_entity="A"))
    seen = V.HiddenLabels(store, "0xab", {"A", None}).lookup_many(list(store.rows))
    assert list(seen) == [("0xef", "ethereum")]


@pytest.mark.parametrize("name", ["tron-ofac", "tron-abstain", "eth-bridge", "tron-terror-link"])
def test_a_slim_case_scores_exactly_as_the_full_case(name, tmp_path):
    case = run_demo(name, tmp_path / "c.duckdb")
    slim = json.loads(json.dumps(V.slim(case)))
    full, kept = R.case_risk(case), R.case_risk(slim)
    assert kept["score"] == full["score"] and kept["risk_class"] == full["risk_class"]
    assert [i["code"] for i in kept["indicators"]] == [i["code"] for i in full["indicators"]]
    assert kept["flows"] == full["flows"] and kept["path_class"] == full["path_class"]


def _view(score_flags=(), edges=1, address="w"):
    """A slim case with the given pattern flags."""
    return {"id": "x", "address": address, "chain": "tron", "status": "done",
            "outcome": "INSUFFICIENT_EVIDENCE", "asset": "USDT", "total_sent": 1.0,
            "top_vasp": None, "candidates": [],
            "typology_flags": [{"code": c, "wallet": "t" if c.endswith("contact") else address,
                                "text": c, "figures": {"share": 1.0, "hops": 1}
                                if c.endswith("contact") else {}, "tx_hashes": ["h"]}
                               for c in score_flags],
            "graph": {"nodes": [], "edges": [{"id": "e", "source": address, "target": "t",
                                              "tx_hash": "h", "direction": "outbound"}] * edges},
            "where_funds_went": [], "hop_rail": []}


def _rows(spec):
    """address -> (arm, flags per view, own label)"""
    wallets, rows = [], {}
    for address, (arm, flags, own) in spec.items():
        wallets.append({"address": address, "chain": "tron", "arm": arm, "stratum": arm})
        rows[address] = {"address": address, "chain": "tron", "own_label": own,
                         "views": {v: _view(flags, address=address) for v in V.VIEWS}}
    return {"seed": 1, "wallets": wallets}, rows


def test_the_tables_count_wallets_per_arm_and_rule():
    listed = {"category": "sanctioned", "entity": "E", "label": "E", "source": "ofac"}
    corpus, rows = _rows({
        "p1": ("positive", ("mixer_contact",), listed),
        "p2": ("positive", ("peel_chain", "fan_out"), listed),
        "c1": ("control", ("fan_out",), None),
        "c2": ("control", (), None),
    })
    rows["c2"]["views"] = {v: _view((), edges=0, address="c2") for v in V.VIEWS}
    rows["p2"]["views"]["entity_hidden"] = {"error": "ProviderError: gone"}
    m = V.measure(corpus, rows)
    main = m["views"]["own_hidden"]
    assert m["positives"] == 2 and m["controls"] == 2 and m["main_view"] == "own_hidden"
    assert main["arms"]["positive"]["high_or_above"] == 1        # the mixer contact
    assert main["arms"]["positive"]["classes"]["medium"] == 1    # peel 20 + fan-out 10
    assert main["arms"]["control"]["high_or_above"] == 0
    assert main["arms"]["control"]["nothing_to_trace"] == 1
    fan_out = next(r for r in main["rules"] if r["code"] == "fan_out")
    assert (fan_out["positive"], fan_out["positive_of"], fan_out["control"],
            fan_out["control_of"]) == (1, 2, 1, 2)
    traced = next(r for r in main["rules_traced"] if r["code"] == "fan_out")
    assert traced["control_of"] == 1
    # as shown, a listed positive is Severe by lookup: the circular figure
    assert m["views"]["as_shown"]["arms"]["positive"]["classes"]["severe"] == 2
    # a view that could not be read is counted as such, never as Low
    hidden = m["views"]["entity_hidden"]["arms"]["positive"]
    assert hidden["could_not_be_read"] == 1 and sum(hidden["classes"].values()) == 1
    assert main["separation"]["auc_score"] == 1.0


def test_a_wallet_of_the_corpus_that_was_never_traced_stops_the_measurement():
    corpus, rows = _rows({"p1": ("positive", (), None)})
    with pytest.raises(ValueError, match="never traced"):
        V.measure(corpus, {})


def test_the_packed_cases_are_written_the_same_way_twice(tmp_path):
    _, rows = _rows({"p1": ("positive", ("fan_in",), None)})
    V.write_cases(tmp_path / "a.gz", rows)
    V.write_cases(tmp_path / "b.gz", rows)
    assert (tmp_path / "a.gz").read_bytes() == (tmp_path / "b.gz").read_bytes()
    assert V.read_cases(tmp_path / "a.gz") == rows


def test_the_corpus_was_fixed_with_a_source_for_every_wallet_and_no_overlap():
    corpus = json.loads((ROOT / "data" / "validation" / "corpus.json").read_text())
    wallets = corpus["wallets"]
    assert corpus["positives"] >= 40 and corpus["controls"] >= 40
    assert len({w["address"] for w in wallets}) == len(wallets)
    assert all(w["source"] and w["source_url"] and w["taken"] for w in wallets)
    assert not any("wazirx" in (w["entity"] or "").lower() for w in wallets if w["arm"] == "positive")


def test_the_tracked_results_are_what_the_tracked_cases_give():
    out = ROOT / "artifacts" / "risk_validation_v1"
    if not (out / "results.json").exists():
        pytest.skip("not measured yet")
    corpus_path = ROOT / "data" / "validation" / "corpus.json"
    m = V.measure(json.loads(corpus_path.read_text()), V.read_cases(out / "cases.json.gz"),
                  config_sha256=V.sha256(R.DEFAULT_PATH), corpus_sha256=V.sha256(corpus_path))
    assert json.loads(json.dumps(m)) == json.loads((out / "results.json").read_text())
