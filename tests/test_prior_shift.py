import numpy as np
import pytest

from vaspfusion.detect.prior_shift import adjust_to_prior, em_prior
from vaspfusion.eval.calibration_report import calibration_report


def _calibrated_at(prior: float, n: int, rng):
    """Posteriors that are exactly calibrated under `prior` (two unit Gaussians, gap 1.5)."""
    y = rng.random(n) < prior
    x = np.where(y, rng.normal(1.5, 1, n), rng.normal(0, 1, n))
    lr = np.exp(1.5 * x - 1.125)
    return y, prior * lr / (prior * lr + (1 - prior))


def _resample(y, p, prevalence, n, rng):
    pos, neg = np.flatnonzero(y), np.flatnonzero(~y)
    k = int(n * prevalence)
    keep = np.concatenate([rng.choice(pos, k, replace=False), rng.choice(neg, n - k, replace=False)])
    return y[keep], p[keep]


def test_equal_priors_leave_probabilities_unchanged():
    p = np.array([0.01, 0.2, 0.7, 0.99])
    assert np.allclose(adjust_to_prior(p, 0.1, 0.1), p, atol=1e-6)


def test_em_recovers_a_lower_deployment_prior():
    rng = np.random.default_rng(0)
    y, p = _calibrated_at(0.30, 400_000, rng)
    yd, pd = _resample(y, p, 0.03, 100_000, rng)
    pi, adj = em_prior(pd, train_prior=0.30)
    assert pi == pytest.approx(0.03, abs=0.01)
    assert adj.mean() == pytest.approx(0.03, abs=0.01)


def test_prior_correction_reduces_calibration_error_under_shift():
    rng = np.random.default_rng(1)
    y, p = _calibrated_at(0.30, 400_000, rng)
    yd, pd = _resample(y, p, 0.03, 100_000, rng)
    rep = calibration_report(yd.astype(int), pd, pd, calib_prior=0.30)
    assert rep["after_prior_shift"]["ece"] < rep["before"]["ece"]
    assert rep["test_prior_em_estimate"] == pytest.approx(0.03, abs=0.01)
