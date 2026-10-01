"""Model scores for the derived labels: who is scored, by which model, and what the
officer reads (mechanics on the toy frame, see classifykit)."""
import json

import polars as pl
import pytest

from classifykit import toy_frame
from vaspfusion.classify.dataset import Run
from vaspfusion.classify.score import fuse, read_scores, score_labels, write_scores
from vaspfusion.classify.train import run
from vaspfusion.discover.crawl import Finding

RULE_TEXT = ("Sweep rule: forwarded 100% of the 100 USDT it received from 1 sender to {e} wallet "
             "HOT (curated list) in 1 sweep, typically 5 minutes after arrival. Gas rule: no "
             "outside gas payer seen. Sweep rule only. Rule confidence 0.68, not calibrated.")


def finding(address, entity, tier="curated", status="derived"):
    return Finding(address=address, chain="toy", entity=entity, category="exchange",
                   kind="deposit", status=status, rule="sweep", confidence=0.68,
                   evidence=RULE_TEXT.format(e=entity), conflict=None, sweep_target="HOT",
                   target_tier=tier, asset="USDT", share=1.0, received="100", forwarded="100",
                   n_deposits=1, n_senders=1, n_sweeps=1, median_delay_s=300.0,
                   gas_verdict="none", gas_payer=None, gas_payer_entity=None, gas_kinds="",
                   n_paid=0, first_sweep_tx="tx", last_sweep_time="2026-09-25T00:00:00Z",
                   complete=True)


@pytest.fixture(scope="module")
def scored():
    df = toy_frame()
    result = run(df)
    positives = df.filter(pl.col("y") == 1)
    findings = tuple(finding(a, g, "published_por" if g == "ExA" else "curated")
                     for a, g in zip(positives["address"], positives["group"]))
    runs = [Run("toy", "toy", None, 50, findings)]
    return df, result, score_labels(df, result, runs)


def test_every_derived_address_is_scored_once_by_a_model_that_never_trained_on_it(scored):
    df, result, rows = scored
    positives = df.filter(pl.col("y") == 1)
    assert [r["address"] for r in rows] == sorted(positives["address"].to_list())
    oof = {r["address"]: r for r in result.oof.to_dicts()}
    ordered = df.sort("address")["address"]
    for r in rows:
        fold = oof[r["address"]]["fold"]
        assert r["scored_by"] == f"cross-fit:{fold}"
        assert r["p"] == round(oof[r["address"]]["p"], 4)
        model = result.folds[fold]
        assert r["address"] not in set(ordered.gather(model.train_idx).to_list())
        assert r["address"] not in set(ordered.gather(model.calib_idx).to_list())


def test_a_model_that_confirms_a_label_gives_it_its_calibrated_value_and_range():
    # the exchange wallet's label weighs 0.85; the rules gave 0.85 x 0.80 = 0.68
    f = fuse(rule_confidence=0.68, weight=0.85, p=0.97, low=0.95, high=0.99)
    assert f == {"basis": "model", "confidence": 0.8245, "confidence_low": 0.8075,
                 "confidence_high": 0.8415}


def test_a_model_that_does_not_confirm_a_label_never_lowers_what_the_rules_established():
    """The rules saw the sweep into a labelled exchange wallet; the model cannot see
    labels, so its doubt about the behaviour is reported, not multiplied in."""
    f = fuse(rule_confidence=0.9025, weight=0.95, p=0.04, low=0.0, high=0.04)
    assert f == {"basis": "rule", "confidence": 0.9025, "confidence_low": None,
                 "confidence_high": None}
    # just under the rules' confidence is still "not confirmed"
    assert fuse(0.9025, 0.95, 0.94, 0.9, 0.96)["basis"] == "rule"


def test_the_low_end_of_a_confirmed_range_is_never_below_the_rules_confidence():
    f = fuse(rule_confidence=0.68, weight=0.85, p=0.9, low=0.7, high=0.95)
    assert f["basis"] == "model" and f["confidence"] == 0.765
    assert f["confidence_low"] == 0.68 and f["confidence_high"] == 0.8075


def test_every_score_row_follows_the_fusion_rule(scored):
    _, _, rows = scored
    assert {r["basis"] for r in rows} <= {"model", "rule"}
    for r in rows:
        weight = 0.95 if r["entity"] == "ExA" else 0.85
        assert r["rule_confidence"] == 0.68
        assert {k: r[k] for k in ("basis", "confidence", "confidence_low",
                                  "confidence_high")} == \
            fuse(0.68, weight, r["p"], r["p_low"], r["p_high"])


def test_the_evidence_keeps_the_rule_text_and_replaces_the_hand_set_confidence(scored):
    from vaspfusion.classify.score import evidence_text
    _, _, rows = scored
    r = next(r for r in rows if r["basis"] == "model")
    assert r["evidence"].startswith("Sweep rule: forwarded 100% of the 100 USDT")
    assert "not calibrated" not in r["evidence"] and "Rule confidence" not in r["evidence"]
    from vaspfusion.explain import fmt
    assert f"Model: {fmt.prob(r['p'])} that an address behaving like this is an exchange " \
           "deposit address" in r["evidence"]
    assert "1.00" not in r["evidence"].split("Model:")[1]
    assert "from a model that did not train on this address" in r["evidence"]
    assert f"Label confidence {r['confidence']:.2f}" in r["evidence"]
    assert r["evidence"].endswith("× the model's probability.")
    kept = evidence_text(RULE_TEXT.format(e="ExA"), "ExA", "curated",
                         {"p": 0.04, "p_low": 0.0, "p_high": 0.04, "basis": "rule",
                          "confidence": 0.68})
    assert kept.endswith("Model: 0.04 that an address behaving like this is an exchange deposit "
                         "address (range under 0.01 to 0.04), from a model that did not train on this "
                         "address. The model reads behaviour only and does not recognise this "
                         "one; it cannot see the sweep into the labelled exchange wallet, so the "
                         "rule confidence 0.68 is kept (hand-set, not calibrated).")
    sure = evidence_text(RULE_TEXT.format(e="ExA"), "ExA", "curated",
                         {"p": 0.9989, "p_low": 0.9989, "p_high": 1.0, "basis": "model",
                          "confidence": 0.8491})
    assert sure.endswith("Model: over 0.99 that an address behaving like this is an exchange "
                         "deposit address (range narrower than 0.01), from a model that did not "
                         "train on this address. Label confidence 0.85 = 0.85 for the ExA "
                         "wallet's label (curated list) × the model's probability.")
    agrees = evidence_text(RULE_TEXT.format(e="ExA"), "ExA", "published_por",
                           {"p": 0.93, "p_low": 0.9, "p_high": 0.95, "basis": "rule",
                            "confidence": 0.9025})
    assert agrees.endswith("The model agrees, but 0.95 × 0.93 is no more than the rules gave, so "
                           "the rule confidence 0.90 is kept (hand-set, not calibrated).")


def test_each_score_carries_the_models_own_numbers_and_reasons(scored):
    _, _, rows = scored
    for r in rows[:20]:
        model = json.loads(r["model"])
        assert (model["p"], model["low"], model["high"]) == (r["p"], r["p_low"], r["p_high"])
        assert model["basis"] == r["basis"] and model["scored_by"] == r["scored_by"]
        assert len(model["reasons"]) == 3
        assert all(set(x) == {"feature", "text", "weight"} for x in model["reasons"])


def test_an_address_two_runs_derived_is_scored_against_the_finding_its_label_keeps(scored):
    """The label loader keeps the more confident of two runs' rows; the floor of the
    fusion must be that row's confidence, not the first run's."""
    from dataclasses import replace
    df, result, _ = scored
    address = df.filter(pl.col("y") == 1)["address"][0]
    group = df.filter(pl.col("address") == address)["group"][0]
    weak = finding(address, group)
    strong = replace(weak, confidence=0.8075, evidence="Sweep rule: stronger run. "
                     "Rule confidence 0.81, not calibrated.")
    for runs in ([Run("a", "toy", None, 50, (weak,)), Run("b", "toy", None, 50, (strong,))],
                 [Run("a", "toy", None, 50, (strong,)), Run("b", "toy", None, 50, (weak,))]):
        (row,) = score_labels(df, result, runs)
        assert row["rule_confidence"] == 0.8075
        assert row["evidence"].startswith("Sweep rule: stronger run.")
        assert row["confidence"] >= 0.8075


def test_addresses_that_are_not_derived_labels_get_no_score(scored):
    df, result, _ = scored
    positives = df.filter(pl.col("y") == 1)["address"].to_list()
    runs = [Run("toy", "toy", None, 50, (finding(positives[0], df["group"][0], status="conflict"),
                                         finding("NOT-IN-DATASET", "ExA")))]
    assert score_labels(df, result, runs) == []


def test_scores_round_trip_and_rewrite_to_the_same_bytes(scored, tmp_path):
    _, _, rows = scored
    path = write_scores(tmp_path / "scores.csv", rows)
    again = write_scores(tmp_path / "again.csv", list(reversed(rows)))
    assert path.read_bytes() == again.read_bytes()
    back = read_scores(path)
    assert back[(rows[0]["address"], "toy")]["confidence"] == rows[0]["confidence"]
    assert back[(rows[0]["address"], "toy")]["confidence_low"] == rows[0]["confidence_low"]
    assert write_scores(tmp_path / "kept.csv", [{**rows[0], "basis": "rule",
                                                 "confidence_low": None,
                                                 "confidence_high": None}])
    assert read_scores(tmp_path / "kept.csv")[(rows[0]["address"], "toy")]["confidence_low"] \
        is None
    assert back[(rows[0]["address"], "toy")]["model"] == rows[0]["model"]
    assert len(back) == len(rows)
