"""Evaluation metrics chosen for a 2-13% positive rate.

Choosing the metric IS a differentiator here, because the obvious one is
worthless: at a 2% positive rate a model that predicts "all licit" scores 98%
accuracy. Accuracy never appears in this file.

  * PR-AUC is the primary. ROC-AUC is misleadingly flattering under heavy class
    imbalance because the huge negative class makes the false-positive rate look
    tiny no matter what.
  * PRECISION@k is the metric the JOB has. An analyst opens the top ten. If eight
    are real, the tool works. Everything else is commentary.
  * EXPECTED CALIBRATION ERROR decides whether "0.87" is a claim or a decoration.
  * HELD-OUT-TYPOLOGY RECALL measures generalisation to laundering patterns never
    trained on. It will be low. Reporting it anyway is the point.

Accuracy and F1 ARE computed, in classification_report_at - but accuracy is only
ever emitted alongside the all-negative baseline that makes its uselessness here
visible. It is never used to judge the system.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score


def pr_auc(y: np.ndarray, s: np.ndarray) -> float:
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(average_precision_score(y, s))


def roc_auc(y: np.ndarray, s: np.ndarray) -> float:
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(roc_auc_score(y, s))


def precision_at_k(y: np.ndarray, s: np.ndarray, k: int) -> float:
    """What fraction of the top k are genuinely illicit."""
    if len(y) == 0:
        return float("nan")
    k = min(k, len(y))
    top = np.argsort(-s)[:k]
    return float(y[top].mean())


def _surrogate(order: np.ndarray) -> np.ndarray:
    """Turn a permutation into a descending score, so rank metrics apply to it."""
    out = np.empty(len(order), dtype=np.float64)
    out[order] = np.arange(len(order), 0, -1)
    return out


def queue_order(confidence: np.ndarray, value_out: np.ndarray, raw: np.ndarray,
                mode: str = "band") -> np.ndarray:
    """The order the analyst is actually shown.

    `band` is what pipeline.py shipped: the calibrated probability rounded to two
    decimals, ties broken by value moved, then by raw score. The reasoning was
    that two entities at 0.93 are not distinguishable, so the bigger money is the
    better lead.

    `score` ranks by the raw fused score at full resolution and uses value only
    for an exact tie - which is what detect/fuse.py says the design is.

    Both are computed on every fold, because the band-vs-score choice is a claim
    about whether the calibrator's discarded resolution carries signal, and that
    is a measurement, not a preference.
    """
    if mode == "score":
        return _surrogate(np.lexsort((-value_out, -raw)))
    return _surrogate(np.lexsort((-raw, -value_out, -np.round(confidence, 2))))


def _rank_block(y: np.ndarray, s: np.ndarray) -> dict:
    return {
        "pr_auc": round(pr_auc(y, s), 4),
        "precision_at_10": round(precision_at_k(y, s, 10), 4),
        "precision_at_25": round(precision_at_k(y, s, 25), 4),
        "precision_at_50": round(precision_at_k(y, s, 50), 4),
    }


def evaluate_queue(y: np.ndarray, confidence: np.ndarray, value_out: np.ndarray,
                   raw: np.ndarray) -> dict:
    """Rank quality of the orderings an analyst could be shown, side by side.

    Every published ranking number scored the calibrated probability, which is
    not what the queue sorts by. That made the scorecard a description of an
    ordering nobody has ever seen.
    """
    return {
        "shipped_band_then_value": _rank_block(
            y, queue_order(confidence, value_out, raw, "band")),
        "raw_score_then_value": _rank_block(
            y, queue_order(confidence, value_out, raw, "score")),
        "model_calibrated_score": _rank_block(y, confidence),
        "note": ("Three orderings of the same scores. raw_score_then_value is what "
                 "pipeline.py ships; shipped_band_then_value is the ordering it "
                 "shipped before (confidence banded to 2dp, value moved breaking the "
                 "tie), kept under its old key so older artefacts stay comparable."),
    }


def recall_at_precision(y: np.ndarray, s: np.ndarray, target: float = 0.8) -> float:
    """How much illicit activity we catch at an acceptable false-alarm rate."""
    if y.sum() == 0:
        return float("nan")
    order = np.argsort(-s)
    ys = y[order]
    tp = np.cumsum(ys)
    prec = tp / np.arange(1, len(ys) + 1)
    ok = prec >= target
    if not ok.any():
        return 0.0
    return float(tp[ok].max() / y.sum())


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Weighted mean gap between predicted probability and observed frequency."""
    if len(y) == 0:
        return float("nan")
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        m = idx == b
        if not m.any():
            continue
        ece += (m.mean()) * abs(p[m].mean() - y[m].mean())
    return float(ece)


def reliability_curve(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    """Points for the reliability diagram in the model panel."""
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        if not m.any():
            continue
        out.append({"bin": b, "predicted": round(float(p[m].mean()), 4),
                    "observed": round(float(y[m].mean()), 4), "n": int(m.sum())})
    return out


def held_out_recall(y: np.ndarray, s: np.ndarray, threshold: float) -> float:
    """Recall on typologies the model never saw, at the operating threshold."""
    if len(y) == 0 or y.sum() == 0:
        return float("nan")
    return float(((s >= threshold) & (y == 1)).sum() / y.sum())


def evaluate(y: np.ndarray, s: np.ndarray, threshold: float = 0.5) -> dict:
    y = np.asarray(y).astype(int)
    s = np.asarray(s, dtype=float)
    return {
        "n": int(len(y)),
        "n_positive": int(y.sum()),
        "positive_rate": round(float(y.mean()) if len(y) else 0.0, 4),
        "pr_auc": round(pr_auc(y, s), 4),
        "roc_auc": round(roc_auc(y, s), 4),
        "precision_at_10": round(precision_at_k(y, s, 10), 4),
        "precision_at_25": round(precision_at_k(y, s, 25), 4),
        "precision_at_50": round(precision_at_k(y, s, 50), 4),
        "recall_at_precision_80": round(recall_at_precision(y, s, 0.8), 4),
        "ece": round(expected_calibration_error(y, s), 4),
        "baseline_pr_auc": round(float(y.mean()) if len(y) else 0.0, 4),
    }


def classification_report_at(y: np.ndarray, s: np.ndarray, threshold: float) -> dict:
    """Confusion matrix and the threshold metrics people ask for by name.

    ACCURACY IS REPORTED BESIDE ITS OWN BASELINE, always. At a 2% positive rate
    "predict everything licit" scores 98%, and quoting accuracy without that
    comparison is the most misleading number this project could publish. MCC is
    included because it is the one single figure that does not collapse under
    class imbalance.
    """
    from sklearn.metrics import (balanced_accuracy_score, confusion_matrix,
                                 matthews_corrcoef, precision_recall_fscore_support)
    y = np.asarray(y).astype(int)
    s = np.asarray(s, dtype=float)
    yp = (s >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, yp, labels=[0, 1]).ravel()
    p, r, f1, _ = precision_recall_fscore_support(y, yp, average="binary", zero_division=0)

    best_f1, best_t = 0.0, float(threshold)
    for t in np.linspace(0.01, 0.99, 99):
        _, _, f, _ = precision_recall_fscore_support(
            y, (s >= t).astype(int), average="binary", zero_division=0)
        if f > best_f1:
            best_f1, best_t = float(f), float(t)

    return {
        "threshold": round(float(threshold), 4),
        "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
        "accuracy": round(float((tp + tn) / max(len(y), 1)), 4),
        "accuracy_all_negative_baseline": round(float(1 - y.mean()) if len(y) else 0.0, 4),
        "precision": round(float(p), 4),
        "recall": round(float(r), 4),
        "f1": round(float(f1), 4),
        "mcc": round(float(matthews_corrcoef(y, yp)) if len(set(yp.tolist())) > 1 else 0.0, 4),
        "balanced_accuracy": round(float(balanced_accuracy_score(y, yp)), 4),
        "best_f1": round(best_f1, 4),
        "best_f1_threshold": round(best_t, 4),
        "note": ("Accuracy is shown beside the all-negative baseline on purpose: at this "
                 "positive rate they are nearly identical, which is exactly why accuracy "
                 "is not used to judge this system. MCC and PR-AUC are."),
    }
