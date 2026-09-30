"""Is "0.87" true where the analyst actually looks?

Global ECE averages over every entity, and at a 0.39% base rate almost every
entity sits in the bottom bin where the calibrator is trivially right. The
analyst reads the top of the queue, so calibration is measured there too. The
report also separates how much of the error is prior shift: the forward-in-time
split makes the calibration fold far richer in positives than the test fold
(bulk: 5.88% vs 0.39%), and isotonic regression learns the fold's prior.
"""
from __future__ import annotations

import numpy as np

from ..detect.prior_shift import adjust_to_prior, em_prior
from . import metrics as M

TOP_K = (10, 25, 60, 200, 1000)


def adaptive_ece(y: np.ndarray, p: np.ndarray, bins: int = 15) -> float:
    """ECE over equal-MASS bins, so the sparse high-probability tail gets its own bins."""
    if len(y) == 0:
        return float("nan")
    order = np.argsort(p, kind="stable")
    total = 0.0
    for chunk in np.array_split(order, bins):
        if len(chunk):
            total += len(chunk) / len(y) * abs(float(p[chunk].mean()) - float(y[chunk].mean()))
    return float(total)


def top_k_reliability(y: np.ndarray, p: np.ndarray, rank_score: np.ndarray,
                      ks=TOP_K) -> list[dict]:
    order = np.lexsort((np.arange(len(y)), -np.asarray(rank_score, dtype=float)))
    out = []
    for k in ks:
        if k > len(y):
            break
        top = order[:k]
        out.append({"k": int(k), "mean_predicted": round(float(p[top].mean()), 4),
                    "observed_precision": round(float(y[top].mean()), 4)})
    return out


def _block(y, p, rank_score) -> dict:
    return {"ece": round(M.expected_calibration_error(y, p), 4),
            "adaptive_ece": round(adaptive_ece(y, p), 4),
            "top_k": top_k_reliability(y, p, rank_score),
            "reliability": M.reliability_curve(y, p)}


def calibration_report(y: np.ndarray, p: np.ndarray, raw: np.ndarray,
                       calib_prior: float) -> dict:
    y = np.asarray(y).astype(int)
    p = np.asarray(p, dtype=float)
    pi_hat, p_adj = em_prior(p, calib_prior)
    true_prior = float(y.mean()) if len(y) else 0.0
    return {
        "calibration_fold_prior": round(float(calib_prior), 4),
        "test_prior_true": round(true_prior, 4),
        "test_prior_em_estimate": round(float(pi_hat), 4),
        "before": _block(y, p, raw),
        "after_prior_shift": _block(y, p_adj, raw),
        "oracle_prior_shift": _block(y, adjust_to_prior(p, calib_prior, true_prior), raw),
        "note": ("before = shipped probabilities. after_prior_shift = EM-estimated test "
                 "prior, no labels used. oracle_prior_shift = the true test prior, the "
                 "best any prior correction could do. top_k ranks by the raw score, "
                 "which is the order the analyst sees."),
    }


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def venn_abers_report(va, y: np.ndarray, raw: np.ndarray, calib_prior: float,
                      pi_hat: float, sample: int = 2000, seed: int = 0) -> dict:
    """Do the intervals contain the observed rate, and how wide are they at the top?"""
    from ..detect.venn_abers import VennAbers
    y = np.asarray(y).astype(int)
    raw = np.asarray(raw, dtype=float)
    rng = np.random.default_rng(seed)
    idx = np.sort(rng.choice(len(y), size=min(sample, len(y)), replace=False))
    p0, p1 = va.interval(raw[idx])

    def bins_of(lo_all: np.ndarray, hi_all: np.ndarray) -> list[dict]:
        out = []
        merged = VennAbers.merge(lo_all, hi_all)
        for chunk in np.array_split(np.argsort(merged, kind="stable"), 10):
            if not len(chunk):
                continue
            lo, hi = float(lo_all[chunk].mean()), float(hi_all[chunk].mean())
            k, n = int(y[idx][chunk].sum()), int(len(chunk))
            # A bin of a few hundred entities carries binomial noise far wider
            # than a Venn-Abers interval, so "consistent" asks whether the
            # interval overlaps the observed rate's own 95% Wilson interval.
            ci_lo, ci_hi = _wilson(k, n)
            out.append({"n": n, "low": round(lo, 4), "high": round(hi, 4),
                        "observed": round(k / n, 4),
                        "observed_wilson_95": [round(ci_lo, 4), round(ci_hi, 4)],
                        "inside": bool(hi >= ci_lo - 1e-9 and lo <= ci_hi + 1e-9)})
        return out

    # Venn-Abers validity assumes calibration and test data are exchangeable. The
    # forward-in-time split breaks that (the calibration fold is richer in
    # positives), so the intervals are reported both as fitted and after the
    # same EM prior correction the point probabilities get.
    bins = bins_of(p0, p1)
    bins_adj = bins_of(adjust_to_prior(p0, calib_prior, pi_hat),
                       adjust_to_prior(p1, calib_prior, pi_hat))
    top = np.lexsort((np.arange(len(y)), -raw))[:60]
    t0, t1 = va.interval(raw[top])
    a0, a1 = adjust_to_prior(t0, calib_prior, pi_hat), adjust_to_prior(t1, calib_prior, pi_hat)
    return {
        "n_sampled": int(len(idx)),
        "mean_width": round(float(np.mean(p1 - p0)), 4),
        "bins_inside": int(sum(b["inside"] for b in bins)),
        "bins": bins,
        "bins_inside_after_prior_shift": int(sum(b["inside"] for b in bins_adj)),
        "bins_after_prior_shift": bins_adj,
        "top_60": {"mean_low": round(float(t0.mean()), 4), "mean_high": round(float(t1.mean()), 4),
                   "observed_precision": round(float(y[top].mean()), 4),
                   "after_prior_shift": {"mean_low": round(float(a0.mean()), 4),
                                         "mean_high": round(float(a1.mean()), 4)}},
    }
