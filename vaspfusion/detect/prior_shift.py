"""Label-shift correction: move calibrated probabilities to another base rate.

Saerens, Latinne & Decaestecker (2002), "Adjusting the outputs of a classifier
to new a priori probabilities: a simple procedure", Neural Computation 14(1).
A posterior calibrated at prior pi_t becomes, at prior pi,
    p' = (pi/pi_t) p / ( (pi/pi_t) p + ((1-pi)/(1-pi_t)) (1-p) ).
When pi is unknown, EM estimates it from the unlabelled scores alone, so it
runs on a live capture exactly as it does on a test fold. It assumes the
class-conditional score distributions did not change - only the mix did.
"""
from __future__ import annotations

import numpy as np

_EPS = 1e-6


def adjust_to_prior(p, train_prior: float, new_prior: float) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), _EPS, 1 - _EPS)
    pt = float(np.clip(train_prior, _EPS, 1 - _EPS))
    pn = float(np.clip(new_prior, _EPS, 1 - _EPS))
    a = (pn / pt) * p
    b = ((1 - pn) / (1 - pt)) * (1 - p)
    return a / (a + b)


def em_prior(p, train_prior: float, tol: float = 1e-7,
             max_iter: int = 500) -> tuple[float, np.ndarray]:
    """(estimated prior, posteriors adjusted to that prior)."""
    p = np.asarray(p, dtype=float)
    if len(p) == 0:
        return float(train_prior), p
    pi = float(train_prior)
    for _ in range(max_iter):
        new = float(adjust_to_prior(p, train_prior, pi).mean())
        done = abs(new - pi) < tol
        pi = new
        if done:
            break
    return pi, adjust_to_prior(p, train_prior, pi)
