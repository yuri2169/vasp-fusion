"""Split-integrity and metric tests carried over from BTC-FUSION's test_core.

Split integrity matters more here, not less: the benchmark splits by exchange and
by time (ROADMAP), and group leakage is silent precisely because it makes numbers
better."""
from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from vaspfusion.eval import metrics as M
from vaspfusion.eval.splits import SplitViolation, verify


def _split_frame():
    return pl.DataFrame({
        "idx": [0, 1, 2, 3], "illicit": [0, 1, 0, 1],
        "typology": ["", "peel_chain", "", "dormancy_burst"],
        "first_ts": [10, 20, 30, 40],
    })


def test_entity_in_two_splits_is_rejected():
    with pytest.raises(SplitViolation, match="leakage"):
        verify(_split_frame(),
               {"train": np.array([0, 1]), "test": np.array([1, 2])}, [])


def test_test_set_before_train_set_is_rejected():
    with pytest.raises(SplitViolation, match="past from the future"):
        verify(_split_frame(),
               {"train": np.array([2, 3]), "test": np.array([0, 1])}, [])


def test_heldout_typology_leaking_into_training_is_rejected():
    # Deliberately temporally VALID (train ts 10,20 < test ts 30,40) so this
    # isolates the typology rule instead of tripping the ordering check first.
    with pytest.raises(SplitViolation, match="not one example"):
        verify(_split_frame(),
               {"train": np.array([0, 1]), "calib": np.array([], dtype=int),
                "test": np.array([2, 3])}, ["peel_chain"])


def test_a_clean_split_passes_all_three_rules():
    verify(_split_frame(),
           {"train": np.array([0, 1]), "calib": np.array([], dtype=int),
            "test": np.array([2, 3])}, ["cross_asn_structuring"])


def test_precision_at_k_reads_the_top_of_the_ranking():
    y = np.array([1, 1, 0, 0, 0])
    s = np.array([0.9, 0.8, 0.7, 0.6, 0.5])
    assert M.precision_at_k(y, s, 2) == 1.0
    assert M.precision_at_k(y, s, 4) == 0.5


def test_ece_is_zero_for_a_perfectly_calibrated_model():
    rng = np.random.default_rng(0)
    p = rng.random(20000)
    y = (rng.random(20000) < p).astype(int)
    assert M.expected_calibration_error(y, p) < 0.02


def test_pr_auc_of_a_random_ranker_approaches_the_base_rate():
    rng = np.random.default_rng(0)
    y = (rng.random(20000) < 0.05).astype(int)
    assert M.pr_auc(y, rng.random(20000)) == pytest.approx(0.05, abs=0.02)
