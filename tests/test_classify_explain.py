"""SHAP reasons in an officer's words (mechanics on the toy frame, see classifykit)."""
import numpy as np
import pytest

from classifykit import toy_frame
from vaspfusion.classify.explain import (base_value, importance_svg, phrase, reasons,
                                         reasons_sentence, reliability_svg)
from vaspfusion.classify.features import FEATURES
from vaspfusion.classify.splits import time_split
from vaspfusion.classify.train import fit, matrix


@pytest.fixture(scope="module")
def fitted():
    df = toy_frame()
    s = time_split(df)
    return fit(df, s["train"], s["calib"], FEATURES), df[s["test"]]


def test_each_address_gets_its_strongest_reasons_with_signed_weights(fitted):
    model, test = fitted
    out = reasons(model, test, top=3)
    assert len(out) == test.height
    sv = model.detector.shap_values(matrix(test, FEATURES))
    for row, shap_row in zip(out, sv):
        assert len(row) == 3
        assert [r["feature"] for r in row] == \
            [FEATURES[i] for i in np.argsort(-np.abs(shap_row), kind="stable")[:3]]
        for r in row:
            assert r["weight"] == pytest.approx(shap_row[FEATURES.index(r["feature"])], abs=1e-4)
            assert r["text"] and r["feature"] not in r["text"]      # words, not column names


def test_all_reasons_add_up_to_the_models_score(fitted):
    model, test = fitted
    full = reasons(model, test, top=len(FEATURES))
    margin = model.detector.model.predict(matrix(test, FEATURES), raw_score=True)
    base = base_value(model)
    for row, m in zip(full, margin):
        assert base + sum(r["weight"] for r in row) == pytest.approx(m, abs=1e-3)


def test_phrases_read_like_an_officers_note():
    assert phrase("forward_ratio", 1.0) == "forwards 100% of what it receives to one wallet"
    assert phrase("gas_outside_share", 0.0) == "pays its own network fees"
    assert phrase("gas_outside_share", 0.75) == \
        "someone else covered the network fee for 75% of its outgoing transfers"
    assert phrase("n_senders", 1) == "receives from 1 sender"
    assert phrase("n_recipients", 12) == "pays out to 12 wallets"
    assert phrase("dwell_median_s", 180) == "moves funds on about 3 minutes after they arrive"
    assert phrase("dwell_median_s", float("nan")) == \
        "no deposit was seen moving on, so the waiting time is unknown"
    assert all(phrase(f, v) for f in FEATURES for v in (0, 1, 3.5, float("nan")))


def test_the_sentence_names_what_speaks_for_and_against():
    text = reasons_sentence([
        {"feature": "forward_ratio", "text": "forwards 100% of what it receives to one wallet",
         "weight": 2.1},
        {"feature": "gas_outside_share", "text": "pays its own network fees", "weight": -0.8},
        {"feature": "n_senders", "text": "receives from 1 sender", "weight": 0.3}])
    assert text == ("For: forwards 100% of what it receives to one wallet; receives from 1 "
                    "sender. Against: pays its own network fees.")
    assert reasons_sentence([{"feature": "n_out", "text": "1 outgoing transfer",
                              "weight": 0.2}]) == "For: 1 outgoing transfer."


def test_the_two_plots_are_svg_files_that_carry_their_numbers():
    bins = [{"bin_mid": 0.05, "predicted": 0.03, "observed": 0.02, "count": 410},
            {"bin_mid": 0.55, "predicted": 0.56, "observed": 0.61, "count": 18},
            {"bin_mid": 0.95, "predicted": 0.97, "observed": 0.98, "count": 902}]
    svg = reliability_svg(bins, title="Tron, latest 20% of addresses", ece=0.012, brier=0.021)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "Tron, latest 20% of addresses" in svg and "902 addresses" in svg
    assert "prefers-color-scheme: dark" in svg
    assert reliability_svg(bins, title="t", ece=0.012, brier=0.021) != svg
    rows = [{"feature": "gas_outside_share", "importance": 0.61},
            {"feature": "forward_ratio", "importance": 0.39}]
    bars = importance_svg(rows, title="x")
    assert "Network fee covered by someone else" in bars and "61%" in bars
    assert "gas_outside_share" not in bars
    assert importance_svg(rows, title="x") == bars
