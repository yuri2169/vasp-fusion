"""Accuracy must always be reported beside the do-nothing baseline.

At a 2% positive rate a model that predicts "all licit" scores 98%. Reporting
accuracy without that comparison is the most misleading thing this project
could put on a slide.
"""
import numpy as np

from vaspfusion.eval.metrics import classification_report_at


def test_confusion_matrix_is_correct():
    y = np.array([1, 1, 0, 0, 0, 0])
    s = np.array([0.9, 0.2, 0.8, 0.1, 0.1, 0.1])
    r = classification_report_at(y, s, 0.5)
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (1, 1, 1, 3)


def test_f1_matches_the_textbook_definition():
    y = np.array([1, 1, 0, 0])
    s = np.array([0.9, 0.9, 0.9, 0.1])
    r = classification_report_at(y, s, 0.5)
    assert round(r["precision"], 4) == round(2 / 3, 4)
    assert r["recall"] == 1.0
    assert round(r["f1"], 4) == round(2 * (2 / 3) / (2 / 3 + 1), 4)


def test_all_negative_baseline_is_reported():
    y = np.concatenate([np.ones(2), np.zeros(98)])
    s = np.zeros(100)
    r = classification_report_at(y, s, 0.5)
    assert r["accuracy_all_negative_baseline"] == 0.98
    assert r["accuracy"] == 0.98      # predicting nothing scores the same


def test_best_f1_threshold_is_found():
    rng = np.random.default_rng(0)
    y = (rng.random(1000) < 0.1).astype(int)
    s = np.clip(y * 0.6 + rng.random(1000) * 0.4, 0, 1)
    r = classification_report_at(y, s, 0.5)
    assert 0.0 < r["best_f1_threshold"] < 1.0
    assert r["best_f1"] >= r["f1"] - 1e-9
