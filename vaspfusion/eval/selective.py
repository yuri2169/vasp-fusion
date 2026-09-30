"""Selective classification: how good is an engine that is allowed to abstain?

A single top-1 figure over "attempted" entities rewards abstaining on every hard
case. The risk-coverage curve shows the whole trade: sort answers by confidence,
and at each coverage (fraction of evaluable entities answered) report the error
rate among the answers given. AURC summarises it; e-AURC subtracts what a
perfect confidence ordering of the same answers would score, so it measures the
confidence ranking alone (Geifman & El-Yaniv 2017; Geifman et al. ICLR 2019).
"""
from __future__ import annotations

import numpy as np


def risk_coverage(confidence: np.ndarray, correct: np.ndarray, n_evaluable: int,
                  n_points: int = 50) -> dict:
    confidence = np.asarray(confidence, dtype=float)
    correct = np.asarray(correct, dtype=bool)
    n = len(correct)
    if n == 0 or n_evaluable <= 0:
        return {"available": False}
    order = np.lexsort((np.arange(n), -confidence))      # ties keep input order
    c = correct[order].astype(float)
    k = np.arange(1, n + 1)
    risk = 1.0 - np.cumsum(c) / k
    coverage = k / float(n_evaluable)
    m = int(n - c.sum())
    oracle = np.clip(k - (n - m), 0, None) / k
    aurc, oracle_aurc = float(risk.mean()), float(oracle.mean())

    def at(cov: float):
        j = int(np.searchsorted(coverage, cov, side="right")) - 1
        return round(float(risk[j]), 4) if j >= 0 else None

    idx = np.unique(np.linspace(0, n - 1, min(n_points, n)).astype(int))
    return {
        "available": True,
        "aurc": round(aurc, 4),
        "e_aurc": round(aurc - oracle_aurc, 4),
        "oracle_aurc": round(oracle_aurc, 4),
        "max_coverage": round(float(coverage[-1]), 4),
        "risk_at_coverage": {"0.25": at(0.25), "0.50": at(0.50), "0.75": at(0.75)},
        "curve": [{"coverage": round(float(coverage[i]), 4),
                   "risk": round(float(risk[i]), 4)} for i in idx],
    }


# Candidate suppression thresholds, fixed in advance. Short on purpose: the
# guarantee below splits delta across the grid, so every extra point costs power.
THRESHOLD_GRID = (0.0, 0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30)
ANSWER_NOTHING = 1.01          # confidence is clipped to 0.99, so this abstains on all
SHARED_EXIT_KINDS = ("vpn", "tor", "cdn")


def risk_controlled_threshold(confidence: np.ndarray, correct: np.ndarray,
                              target_risk: float = 0.05, delta: float = 0.05,
                              grid: tuple[float, ...] = THRESHOLD_GRID) -> dict:
    """Lowest suppression threshold whose attribution error stays under target_risk.

    Fitted on the CALIBRATION fold. For a threshold t the answered set is every
    entity whose top candidate has confidence >= t, and its error rate gets a
    one-sided Clopper-Pearson upper bound at level delta / len(grid). By the union
    bound, with probability >= 1 - delta every tested threshold that passes has a
    true error rate at most target_risk, so the lowest passing one (the most
    leads answered) is safe whichever it is. Two alternatives were measured and
    rejected: a 31-point grid split delta so thinly that reliable classes with a
    few hundred calibration examples could not pass; fixed-sequence testing from
    the top down stopped at the first failure, and attribution error is not
    monotone in the threshold (relays can score high), so it abstained on
    reliable classes too.
    """
    from scipy.stats import beta
    conf = np.asarray(confidence, dtype=float)
    ok = np.asarray(correct, dtype=bool)
    d = delta / len(grid)
    rows, chosen = [], None
    for t in sorted(grid):
        m = conf >= t
        n = int(m.sum())
        k = int((~ok[m]).sum())
        ub = float(beta.ppf(1 - d, k + 1, n - k)) if 0 < n and k < n else 1.0
        row = {"threshold": t, "n_answered": n, "errors": k,
               "risk": round(k / n, 4) if n else None, "risk_upper_bound": round(ub, 4)}
        rows.append(row)
        if chosen is None and n > 0 and ub <= target_risk:
            chosen = row
    base = {"target_risk": target_risk, "delta": delta, "n_calibration": int(len(conf)),
            "grid": rows}
    if chosen is None:
        return {**base, "attainable": False, "threshold": ANSWER_NOTHING,
                "n_answered": 0, "errors": 0, "risk": None, "risk_upper_bound": 1.0}
    return {**base, "attainable": True, **chosen}


def class_conditional_threshold(confidence: np.ndarray, correct: np.ndarray,
                                classes: np.ndarray, target_risk: float = 0.05,
                                delta: float = 0.05, min_n: int = 30) -> dict:
    """One risk-controlled threshold per candidate network class.

    A single pooled threshold lets reliable classes (residential, mobile) carry
    unreliable ones (VPN, Tor and CDN exits, which are never an entity's own
    address): on the demo test fold 85 answers named a shared exit and none were
    right. Fitting each class separately, with delta split across the classes
    (Bonferroni), keeps every class's error under target_risk with probability
    >= 1 - delta; a class with too little calibration data abstains. "*" is the
    pooled policy, used for a class never seen in calibration.
    """
    conf = np.asarray(confidence, dtype=float)
    ok = np.asarray(correct, dtype=bool)
    cls = np.asarray(classes).astype(str)
    names = sorted(set(cls.tolist()))
    d = delta / (len(names) + 1)
    by_class, tmap = {}, {}
    for c in names:
        m = cls == c
        if int(m.sum()) < min_n:
            by_class[c] = {"attainable": False, "threshold": ANSWER_NOTHING,
                           "n_calibration": int(m.sum()), "reason": f"fewer than {min_n} examples"}
        else:
            p = risk_controlled_threshold(conf[m], ok[m], target_risk, d)
            by_class[c] = {k: v for k, v in p.items() if k != "grid"}
        tmap[c] = by_class[c]["threshold"]
    # A shared exit is never an entity's own address: never answer one, whatever
    # a finite calibration sample says, and never let it fall through to "*".
    for key in list(tmap):
        if key.split("|")[0] in SHARED_EXIT_KINDS:
            tmap[key] = ANSWER_NOTHING
    for kind in SHARED_EXIT_KINDS:
        tmap.setdefault(kind, ANSWER_NOTHING)
    pooled = risk_controlled_threshold(conf, ok, target_risk, d)
    tmap["*"] = pooled["threshold"]
    return {"kind": "class_conditional", "target_risk": target_risk, "delta": delta,
            "threshold_map": tmap, "by_class": by_class,
            "pooled": {k: v for k, v in pooled.items() if k != "grid"}}
