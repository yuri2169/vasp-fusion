"""Confidence strength and its interval - the chain-agnostic parts of BTC-FUSION's
attribution confidence.

BTC-FUSION's version multiplied in network-observation factors (propagation roots,
shared-infrastructure penalties, timezone agreement). Those are IP-level signals
this project does not have, so they were dropped in the fork. What survives is the
part that carries over to on-chain attribution: an evidence strength built from a
significance and a magnitude, and an interval that widens as evidence thins.
B3 builds the rule-based confidence on top of this; B6 replaces it with a
calibrated model; B7 adds the counterfactual check.
"""
from __future__ import annotations

import numpy as np


def significance_strength(p_value: float, ppmi: float) -> float:
    """Turn a p-value and a PMI magnitude into a [0,1] base strength.

    The p-value says "not chance"; the PMI says "how strongly". A link can be
    highly significant and still weak, so both are needed and the geometric mean
    keeps either one from dominating.
    """
    sig = float(np.clip(-np.log10(max(p_value, 1e-300)) / 12.0, 0.0, 1.0))
    mag = float(np.clip(ppmi / 4.0, 0.0, 1.0))
    return float(np.sqrt(max(sig, 1e-9) * max(mag, 1e-9)))


def interval(conf: float, n_obs: int) -> float:
    """Half-width that widens as evidence thins (Wilson-style)."""
    n = max(1, int(n_obs))
    half = 1.96 * np.sqrt(max(conf * (1 - conf), 1e-4) / n)
    return float(np.clip(half, 0.02, 0.45))
