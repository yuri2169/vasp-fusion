"""Model scores for the derived labels: who is scored, by which model, and what the
officer reads (mechanics on the toy frame, see classifykit)."""
import json

import polars as pl
import pytest

from classifykit import toy_frame
from vaspfusion.classify.dataset import Run
from vaspfusion.classify.score import read_scores, score_labels, write_scores
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


def test_label_confidence_is_the_exchange_wallets_weight_times_the_probability(scored):
    _, _, rows = scored
    for r in rows:
        weight = 0.95 if r["entity"] == "ExA" else 0.85
        assert r["confidence"] == pytest.approx(weight * r["p"], abs=1e-4)
        assert r["confidence_low"] == pytest.approx(weight * r["p_low"], abs=1e-4)
        assert r["confidence_high"] == pytest.approx(weight * r["p_high"], abs=1e-4)
        assert 0 <= r["confidence_low"] <= r["confidence"] <= r["confidence_high"] <= 1


def test_the_evidence_keeps_the_rule_text_and_replaces_the_hand_set_confidence(scored):
    _, _, rows = scored
    r = rows[0]
    assert r["evidence"].startswith("Sweep rule: forwarded 100% of the 100 USDT")
    assert "not calibrated" not in r["evidence"] and "Rule confidence" not in r["evidence"]
    assert f"Model: {r['p']:.2f} that this is an exchange deposit address" in r["evidence"]
    assert "from a model that did not train on this address" in r["evidence"]
    assert f"Label confidence {r['confidence']:.2f}" in r["evidence"]


def test_each_score_carries_its_reasons(scored):
    _, _, rows = scored
    for r in rows[:20]:
        reasons = json.loads(r["reasons"])
        assert len(reasons) == 3
        assert all(set(x) == {"feature", "text", "weight"} for x in reasons)


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
    assert back[(rows[0]["address"], "toy")]["reasons"] == rows[0]["reasons"]
    assert len(back) == len(rows)
