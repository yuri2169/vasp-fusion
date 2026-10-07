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
    m = V.measure(corpus, rows, {**R.load_config(), "pattern_cap": None})
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
    # with the cap the two patterns of p2 no longer reach Medium
    capped = V.measure(corpus, rows)["views"]["own_hidden"]["arms"]["positive"]
    assert capped["classes"]["medium"] == 0 and capped["high_or_above"] == 1
    assert main["positives_high_with_list_link"] == 1
    assert main["rules_firing_more_on_positives"] == []      # 1 of 2 against 1 of 2


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


SETS = {"v1": ("corpus.json", lambda: ROOT / "artifacts" / "risk_validation_v1" / "risk.yaml"),
        "v2": ("corpus_v2.json", lambda: R.DEFAULT_PATH)}


@pytest.mark.parametrize("name", list(SETS))
def test_each_set_was_fixed_with_a_source_for_every_wallet(name):
    corpus = json.loads((ROOT / "data" / "validation" / SETS[name][0]).read_text())
    wallets = corpus["wallets"]
    assert corpus["positives"] >= 40 and corpus["controls"] >= 40
    assert len({w["address"] for w in wallets}) == len(wallets)
    assert all(w["source"] and w["source_url"] and w["taken"] for w in wallets)
    assert not any("wazirx" in (w["entity"] or "").lower() for w in wallets if w["arm"] == "positive")


def test_the_fresh_set_holds_no_wallet_of_the_first():
    first, fresh = (json.loads((ROOT / "data" / "validation" / SETS[n][0]).read_text())
                    for n in ("v1", "v2"))
    assert not {w["address"] for w in first["wallets"]} & {w["address"] for w in fresh["wallets"]}
    assert fresh["seed"] != first["seed"] and fresh["excludes"] == ["data/validation/corpus.json"]


@pytest.mark.parametrize("name", list(SETS))
def test_the_tracked_results_are_what_the_tracked_cases_give(name):
    out = ROOT / "artifacts" / f"risk_validation_{name}"
    corpus_path, config_path = ROOT / "data" / "validation" / SETS[name][0], SETS[name][1]()
    m = V.measure(json.loads(corpus_path.read_text()), V.read_cases(out / "cases.json.gz"),
                  R.load_config(config_path), config_sha256=V.sha256(config_path),
                  corpus_sha256=V.sha256(corpus_path), version=f"risk_validation_{name}")
    assert json.loads(json.dumps(m)) == json.loads((out / "results.json").read_text())


def test_the_first_set_keeps_the_points_it_was_measured_with():
    """The first measurement is a record: it is scored with the copy of the points kept
    beside it (no pattern cap), whatever config/risk.yaml says today."""
    old = R.load_config(ROOT / "artifacts" / "risk_validation_v1" / "risk.yaml")
    m = json.loads((ROOT / "artifacts" / "risk_validation_v1" / "results.json").read_text())
    assert old["pattern_cap"] is None and m["pattern_cap"] is None
    arms = m["views"]["own_hidden"]["arms"]
    assert (arms["positive"]["high_or_above"], arms["control"]["high_or_above"]) == (14, 2)
    assert R.load_config()["pattern_cap"] == 20


def test_the_wazirx_statement_says_what_the_trace_table_holds():
    table = json.loads((ROOT / "artifacts" / "wazirx_2024" / "trace_table.json").read_text())
    source = json.loads((ROOT / "data" / "validation" / "wazirx_2024.json").read_text())
    statement = SPECS["wazirx-2024"]["documented"]["statement"]
    rows = table["rows"]
    assert len(rows) == len(source["addresses"]) == 27
    mixer = sum(r["as_shown"]["outcome"] == "SANCTIONED_OR_MIXER_REACHED" for r in rows)
    assert f"{mixer} of the 27 tagged wallets reach Tornado Cash" in statement
    cashed_out = [r["tag"] for r in rows for view in ("as_shown", "entity_hidden")
                  if any(x["direction"] == "outbound" for x in r[view]["exchanges"])]
    assert cashed_out == [] and "none reaches a named exchange within 3 hops" in statement
    main = next(r for r in rows if r["address"] == SPECS["wazirx-2024"]["address"])
    assert [(x["vasp"], x["direction"]) for x in main["as_shown"]["exchanges"]] == \
        [("WazirX", "inbound")]


def test_the_sentence_that_travels_with_the_score_quotes_the_fresh_set():
    from vaspfusion.api.schemas import RISK_BASIS, RiskValidation
    m = json.loads((ROOT / "artifacts" / "risk_validation_v2" / "results.json").read_text())
    arms = m["views"]["own_hidden"]["arms"]
    p, c = arms["positive"], arms["control"]
    assert f"{p['high_or_above']} of {p['wallets']} and {c['high_or_above']} of {c['wallets']}" \
        in RISK_BASIS
    assert "not measured" not in RISK_BASIS and "none of them used to set the points" in RISK_BASIS
    shown = RiskValidation.model_validate(V.summary(m))
    assert shown.main_view == "own_hidden" and len(shown.views) == 3 and len(shown.rules) == 5
    assert m["risk_config_sha256"] == V.sha256(R.DEFAULT_PATH)   # scored with today's points
    assert m["pattern_cap"] == R.load_config()["pattern_cap"]
