"""Inductive Venn-Abers: a calibrated probability INTERVAL per lead.

Vovk & Petej (2014), "Venn-Abers predictors", UAI. For a test score s, fit
isotonic regression on the calibration set plus (s, label 0) and again plus
(s, label 1); the two fitted values at s bound the probability. The width is an
honest statement of how much calibration data sits near that score, which a
point estimate from one isotonic fit cannot express.
"""
from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression


class VennAbers:
    def __init__(self, max_calib: int = 50_000, seed: int = 0):
        self.max_calib = max_calib
        self.seed = seed
        self.s: np.ndarray | None = None
        self.y: np.ndarray | None = None

    def fit(self, scores, y) -> "VennAbers":
        s = np.asarray(scores, dtype=float)
        y = np.asarray(y, dtype=float)
        if len(s) > self.max_calib:
            # A uniform sample keeps the calibration fold's base rate.
            idx = np.random.default_rng(self.seed).choice(len(s), self.max_calib, replace=False)
            s, y = s[idx], y[idx]
        self.s, self.y = s, y
        return self

    def interval(self, scores) -> tuple[np.ndarray, np.ndarray]:
        # ponytail: one O(n) isotonic fit per point and label. Fine for the <=60
        # leads on screen and a 2,000-point evaluation sample; switch to the
        # O(n log n) IVAP of Vovk et al. (2015) if thousands of points are needed.
        scores = np.asarray(scores, dtype=float)
        p0 = np.empty(len(scores))
        p1 = np.empty(len(scores))
        for i, s in enumerate(scores):
            xs = np.append(self.s, s)
            for lab, out in ((0.0, p0), (1.0, p1)):
                iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
                iso.fit(xs, np.append(self.y, lab))
                out[i] = float(iso.predict([s])[0])
        return p0, p1

    @staticmethod
    def merge(p0: np.ndarray, p1: np.ndarray) -> np.ndarray:
        return p1 / (1.0 - p0 + p1)


def lead_intervals(calib_raw, calib_y, raw, prior_from: float | None = None,
                   prior_to: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Per-lead probability range, optionally moved to the capture's base rate."""
    from .prior_shift import adjust_to_prior
    lo, hi = VennAbers().fit(calib_raw, calib_y).interval(raw)
    if prior_from is not None and prior_to is not None:
        lo, hi = adjust_to_prior(lo, prior_from, prior_to), adjust_to_prior(hi, prior_from, prior_to)
    return lo, hi
