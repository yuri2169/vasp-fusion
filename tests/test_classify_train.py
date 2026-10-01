"""Training, calibration and measurement of the deposit-address model: the mechanics,
on a toy frame (classifykit). The real numbers are checked in test_classify_real.py."""
import json

import numpy as np
import polars as pl
import pytest

from classifykit import GROUPS, toy_frame
from vaspfusion.classify.features import FEATURES, LABEL_FEATURES
from vaspfusion.classify.splits import exchange_folds, time_split
from vaspfusion.classify.train import (evaluate, fit, hide_exchange, load_model, predict, run,
                                       save)


@pytest.fixture(scope="module")
def df():
    return toy_frame()


@pytest.fixture(scope="module")
def result(df):
    return run(df)


def test_a_fitted_model_gives_a_probability_inside_its_range(df):
    s = time_split(df)
    m = fit(df, s["train"], s["calib"], FEATURES)
    pred = predict(m, df[s["test"]])
    assert set(pred) == {"raw", "low", "high", "p"}
    assert len(pred["p"]) == len(s["test"])
    assert ((0 <= pred["low"]) & (pred["low"] <= pred["p"]) & (pred["p"] <= pred["high"])
            & (pred["high"] <= 1)).all()
    assert pred["p"][df["y"].gather(s["test"]).to_numpy() == 1].mean() > 0.7


def test_the_model_only_reads_the_features_it_was_given(df):
    s = time_split(df)
    m = fit(df, s["train"], s["calib"], FEATURES)
    changed = df.with_columns(pl.lit(0.0).alias("to_exchange_share"),
                              pl.Series("address", [f"Z{i}" for i in range(df.height)]))
    assert (predict(m, df)["raw"] == predict(m, changed)["raw"]).all()


def test_evaluate_reports_the_metrics_of_the_brief():
    y = np.array([1, 1, 1, 0, 0, 0, 1, 0])
    p = np.array([0.9, 0.8, 0.95, 0.1, 0.2, 0.05, 0.4, 0.6])
    m = evaluate(y, {"p": p, "low": p - 0.05, "high": p + 0.05, "raw": p})
    assert (m["n"], m["n_positive"]) == (8, 4)
    assert m["brier"] == pytest.approx(float(np.mean((p - y) ** 2)), abs=1e-4)
    assert m["pr_auc"] == pytest.approx(0.95, abs=1e-4) and 0 <= m["ece"] <= 1
    assert m["at_0_5"]["tp"] == 3 and m["at_0_5"]["fp"] == 1
    assert m["interval_mean_width"] == pytest.approx(0.1)
    assert sum(b["count"] for b in m["reliability"]) == 8
    assert m["confident"] == {"threshold": 0.9, "coverage": 0.5, "accuracy": 1.0}


def test_one_class_in_the_test_set_gives_no_ranking_metric_rather_than_a_made_up_one():
    y = np.ones(4, dtype=int)
    p = np.array([0.9, 0.8, 0.7, 0.6])
    m = evaluate(y, {"p": p, "low": p, "high": p, "raw": p})
    assert m["pr_auc"] is None and m["roc_auc"] is None
    json.dumps(m, allow_nan=False)


def test_hiding_an_exchange_blanks_its_label_features_everywhere(df):
    hidden = hide_exchange(df, "ExB")
    was = df.filter(pl.col("label_entity") == "ExB")
    now = hidden.filter(pl.col("label_entity") == "ExB")
    assert was["to_exchange_share"].sum() > 0 and now["to_exchange_share"].sum() == 0
    assert now["gas_from_exchange_share"].sum() == 0
    other = pl.col("label_entity") != "ExB"
    assert hidden.filter(other).equals(df.filter(other))
    assert hidden.select(FEATURES).equals(df.select(FEATURES))


def test_run_measures_by_time_and_by_exchange(result):
    m = result.metrics
    assert m["version"] == "model_v1" and m["seed"] == 26182 and m["features"] == FEATURES
    t = m["time_split"]
    assert {"train", "calib", "test"} <= set(t["sizes"]) and t["test"]["n"] == t["sizes"]["test"]
    for key in ("pr_auc", "roc_auc", "brier", "ece", "adaptive_ece", "reliability", "at_0_5"):
        assert key in t["test"]
    table = m["leave_one_exchange_out"]["folds"]
    assert [row["exchange"] for row in table] == list(GROUPS)
    assert all(row["n"] == 80 and row["n_positive"] == 40 for row in table)
    assert m["leave_one_exchange_out"]["pooled"]["n"] == 240
    assert sum(f["importance"] for f in m["feature_importance"]) == pytest.approx(1, abs=1e-3)
    assert {f["feature"] for f in m["feature_importance"]} == set(FEATURES)
    assert "strict_over_gate" in m["leak_audit"]
    json.dumps(m, allow_nan=False)


def test_look_alike_negatives_are_measured_on_their_own(df, result):
    """Positives forward 90% or more by construction, so the test that matters is on the
    negatives that do the same."""
    t = result.metrics["time_split"]
    test_rows = df.sort("address")[time_split(df.sort("address"))["test"]]
    alike = test_rows.filter((pl.col("y") == 0) & (pl.col("forward_ratio") >= 0.9))
    assert t["look_alikes"]["negatives"] == alike.height > 0
    assert 0 <= t["look_alikes"]["false_positive_rate"] <= 1
    assert t["look_alikes"]["flagged"] == round(
        t["look_alikes"]["false_positive_rate"] * alike.height)
    pooled = result.metrics["leave_one_exchange_out"]["look_alikes"]
    assert pooled["negatives"] == df.filter((pl.col("y") == 0)
                                            & (pl.col("forward_ratio") >= 0.9)).height


def test_every_address_is_scored_once_by_a_model_that_never_trained_on_it(df, result):
    oof = result.oof
    assert sorted(oof["address"].to_list()) == sorted(df["address"].to_list())
    assert sorted(result.folds) == [f"block {j}" for j in range(1, 6)]
    by_address = dict(zip(oof["address"].to_list(), oof["fold"].to_list()))
    ordered = df.sort("address")["address"]
    for fold, model in result.folds.items():
        seen = set(ordered.gather(model.train_idx).to_list()) \
            | set(ordered.gather(model.calib_idx).to_list())
        scored = {a for a, f in by_address.items() if f == fold}
        assert scored and not scored & seen


def test_each_exchange_table_row_comes_from_a_model_that_never_saw_the_exchange(df, result):
    ordered = df.sort("address")
    assert sorted(result.by_exchange) == list(GROUPS)
    for exchange, model in result.by_exchange.items():
        assert exchange not in set(ordered["group"].gather(model.train_idx).to_list())
        assert exchange not in set(ordered["group"].gather(model.calib_idx).to_list())


def test_the_cross_fit_scores_are_measured_too(result):
    c = result.metrics["cross_fit"]
    assert c["blocks"] == 5 and c["pooled"]["n"] == 240
    assert [row["exchange"] for row in c["by_exchange"]] == list(GROUPS)
    assert all(row["n_positive"] == 40 for row in c["by_exchange"])
    assert c["look_alikes"]["negatives"] > 0


def test_the_label_ablation_collapses_on_an_exchange_whose_labels_are_hidden(result):
    """Positives were picked by the label features, so a model that reads them is the
    rule again: perfect when it has the labels, blind when the exchange is new."""
    ab = result.metrics["ablation_label_features"]
    assert ab["features"] == FEATURES + LABEL_FEATURES
    assert ab["time_split"]["pr_auc"] >= 0.99
    shipped = result.metrics["leave_one_exchange_out"]["pooled"]["at_0_5"]["recall"]
    assert ab["leave_one_exchange_out"]["pooled"]["at_0_5"]["recall"] < shipped


def test_two_runs_give_the_same_numbers(df, result):
    again = run(df)
    assert again.metrics == result.metrics
    assert again.oof.equals(result.oof)


def test_a_saved_model_scores_the_same_after_loading(df, result, tmp_path):
    save(result, tmp_path)
    assert json.loads((tmp_path / "metrics.json").read_text()) == result.metrics
    model = load_model(tmp_path)
    a, b = predict(result.final, df), predict(model, df)
    assert all((a[k] == b[k]).all() for k in a)
    assert model.features == FEATURES
