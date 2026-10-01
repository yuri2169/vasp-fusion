"""Train, calibrate and measure the deposit-address model (B6).

The model is `detect/supervised.py`'s gradient-boosted trees (LightGBM) on the
behaviour features. Its raw score is turned into a probability with a range by
`detect/venn_abers.py`, fitted on a calibration fold the trees never saw.

Three measurements, all on addresses the model did not train on:

* by time: train on the earliest addresses, test on the latest;
* by exchange (leave one exchange out): hold out everything of one exchange and
  ask whether its deposit addresses are recognised from the other exchanges';
* the label ablation: the same two, with the two features that read exchange
  labels added. On a held-out exchange those labels are hidden, as they would be
  for an exchange nobody has labelled yet.

Every address also gets a cross-fit score: each exchange's addresses are cut into
consecutive blocks by time, and a block is scored by a model trained on the other
blocks. Those are the scores the labels are given (score.py), so no address is
ever scored by a model that trained on it. The leave-one-exchange-out scores are
not used for labels: an exchange we hold labels for is not an unknown exchange.

Probabilities are calibrated at this dataset's class mix (the negatives are a
capped sample), not at the mix of the chain at large.
"""
from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import polars as pl

from ..detect.supervised import SupervisedDetector
from ..detect.venn_abers import VennAbers
from ..eval import metrics as M
from ..eval.calibration_report import _wilson, adaptive_ece
from ..eval.leak_audit import audit
from ..eval.selective import risk_coverage
from .features import FEATURES, LABEL_FEATURES
from .splits import crossfit_folds, exchange_folds, time_split

SEED = 26182
VERSION = "model_v1"
CONFIDENT = 0.9
_SCORE_DECIMALS = 6      # raw scores are rounded so equal scores share one calibration fit


@dataclass
class Fitted:
    detector: SupervisedDetector
    va: VennAbers
    features: list[str]
    train_idx: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=int))
    calib_idx: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=int))


@dataclass
class Result:
    metrics: dict
    final: Fitted                       # the time-split model: scores addresses found later
    folds: dict[str, Fitted]            # cross-fit block -> the model that did not see it
    oof: pl.DataFrame                   # address, fold, raw, p, low, high (cross-fit)
    by_exchange: dict[str, Fitted] = field(default_factory=dict)   # exchange -> its fold


def matrix(df: pl.DataFrame, features: list[str]) -> np.ndarray:
    return df.select(features).to_numpy().astype(np.float64)


def _raw(detector: SupervisedDetector, X: np.ndarray) -> np.ndarray:
    return np.round(detector.predict_proba(X), _SCORE_DECIMALS)


def fit(df: pl.DataFrame, train_idx, calib_idx, features: list[str],
        seed: int = SEED) -> Fitted:
    X, y = matrix(df, features), df["y"].to_numpy().astype(int)
    detector = SupervisedDetector(seed=seed).fit(X[train_idx], y[train_idx], features)
    va = VennAbers(seed=seed).fit(_raw(detector, X[calib_idx]), y[calib_idx])
    return Fitted(detector, va, list(features), np.asarray(train_idx), np.asarray(calib_idx))


def predict(model: Fitted, df: pl.DataFrame) -> dict[str, np.ndarray]:
    """raw score, the Venn-Abers range (low, high) and the probability inside it."""
    raw = _raw(model.detector, matrix(df, model.features))
    scores, inverse = np.unique(raw, return_inverse=True)
    p0, p1 = model.va.interval(scores)
    low, high = np.minimum(p0, p1)[inverse], np.maximum(p0, p1)[inverse]
    p = np.clip(VennAbers.merge(low, high), low, high)
    return {"raw": raw, "low": low, "high": high, "p": p}


def _num(x: float, digits: int = 4) -> float | None:
    return None if x != x else round(float(x), digits)


def _reliability(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    out = []
    for b in M.reliability_curve(y, p, bins):
        out.append({"bin_mid": round((b["bin"] + 0.5) / bins, 2), "predicted": b["predicted"],
                    "observed": b["observed"], "count": b["n"]})
    return out


def _range_check(y: np.ndarray, pred: dict, bins: int = 10) -> dict:
    """Does the range hold the observed rate? Per equal-size group of addresses, the
    mean range against the observed rate's own 95% Wilson interval."""
    rows = []
    for chunk in np.array_split(np.argsort(pred["p"], kind="stable"), min(bins, len(y))):
        if not len(chunk):
            continue
        lo, hi = float(pred["low"][chunk].mean()), float(pred["high"][chunk].mean())
        k, n = int(y[chunk].sum()), int(len(chunk))
        w_lo, w_hi = _wilson(k, n)
        rows.append({"count": n, "low": round(lo, 4), "high": round(hi, 4),
                     "observed": round(k / n, 4),
                     "observed_wilson_95": [round(w_lo, 4), round(w_hi, 4)],
                     "consistent": bool(hi >= w_lo - 1e-9 and lo <= w_hi + 1e-9)})
    return {"groups": rows, "consistent": sum(r["consistent"] for r in rows)}


def evaluate(y, pred: dict) -> dict:
    y = np.asarray(y).astype(int)
    p = np.asarray(pred["p"], dtype=float)
    at = M.classification_report_at(y, p, 0.5)
    sure = np.maximum(p, 1 - p) >= CONFIDENT
    right = (p >= 0.5) == (y == 1)
    # answer the surest addresses first: how accurate is the model at each coverage?
    curve = risk_coverage(np.maximum(p, 1 - p), right, len(y), n_points=25).get("curve", [])
    return {
        "n": int(len(y)), "n_positive": int(y.sum()),
        "pr_auc": _num(M.pr_auc(y, p)), "roc_auc": _num(M.roc_auc(y, p)),
        "brier": _num(float(np.mean((p - y) ** 2))),
        "ece": _num(M.expected_calibration_error(y, p)),
        "adaptive_ece": _num(adaptive_ece(y, p)),
        "interval_mean_width": _num(float(np.mean(pred["high"] - pred["low"]))),
        "at_0_5": {k: at[k] for k in ("tp", "fp", "fn", "tn", "precision", "recall", "f1",
                                      "mcc", "accuracy", "accuracy_all_negative_baseline")},
        "confident": {"threshold": CONFIDENT, "coverage": _num(float(sure.mean())),
                      "accuracy": _num(float(right[sure].mean())
                                       if sure.any() else float("nan"))},
        "reliability": _reliability(y, p),
        "range_check": _range_check(y, pred),
        "risk_coverage": [{"coverage": c["coverage"], "accuracy": round(1 - c["risk"], 4)}
                          for c in curve],
    }


def look_alikes(df: pl.DataFrame, p: np.ndarray, share: float = 0.9) -> dict:
    """The negatives that behave like the positives were chosen to (they forward `share`
    or more of what they receive to one wallet), and how many the model still calls a
    deposit address. Every positive forwards that much by construction, so this is the
    part of the negative class that the forwarding share alone cannot separate."""
    alike = ((df["y"] == 0) & (df["forward_ratio"].fill_null(-1.0) >= share)).to_numpy()
    flagged = int((p[alike] >= 0.5).sum())
    n = int(alike.sum())
    return {"forwarding_at_least": share, "negatives": n, "flagged": flagged,
            "false_positive_rate": round(flagged / n, 4) if n else None}


def hide_exchange(df: pl.DataFrame, exchange: str) -> pl.DataFrame:
    """The dataset as it would look if `exchange` had no labelled wallet: the label
    features that came from its labels are 0, for every row, on either side of a split."""
    theirs = pl.col("label_entity") == exchange
    return df.with_columns([pl.when(theirs).then(0.0).otherwise(pl.col(f)).alias(f)
                            for f in LABEL_FEATURES])


def _sizes(df: pl.DataFrame, split: dict) -> dict:
    y = df["y"].to_numpy()
    return {k: int(len(v)) for k, v in split.items()} | {
        f"{k}_positive": int(y[v].sum()) for k, v in split.items()}


def _by_exchange(df: pl.DataFrame, features: list[str], seed: int, hide: bool,
                 min_positives: int) -> tuple[dict, dict[str, Fitted], pl.DataFrame]:
    y_all = df["y"].to_numpy().astype(int)
    table, models, parts = [], {}, []
    for exchange, split in exchange_folds(df, min_positives=min_positives):
        view = hide_exchange(df, exchange) if hide else df
        model = fit(view, split["train"], split["calib"], features, seed)
        pred = predict(model, view[split["test"]])
        table.append(_table_row(exchange, evaluate(y_all[split["test"]], pred), split))
        models[exchange] = model
        parts.append(pl.DataFrame({
            "address": df["address"].gather(split["test"]),
            "fold": [exchange] * len(split["test"]), "y": y_all[split["test"]],
            **{k: pred[k] for k in ("raw", "p", "low", "high")}}))
    oof = pl.concat(parts).sort("address")
    pooled = evaluate(oof["y"].to_numpy(), {k: oof[k].to_numpy()
                                            for k in ("raw", "p", "low", "high")})
    return {"folds": table, "pooled": pooled}, models, oof.drop("y")


def _table_row(name: str, row: dict, split: dict | None = None) -> dict:
    out = {"exchange": name, **{k: row[k] for k in (
        "n", "n_positive", "pr_auc", "roc_auc", "brier", "ece", "interval_mean_width")},
        "precision": row["at_0_5"]["precision"], "recall": row["at_0_5"]["recall"]}
    if split is not None:
        out |= {"train": int(len(split["train"])), "calib": int(len(split["calib"]))}
    return out


def _cross_fit(df: pl.DataFrame, features: list[str], seed: int, k: int,
               min_positives: int) -> tuple[dict, dict[str, Fitted], pl.DataFrame]:
    """Every address scored once by a model that did not train on it (splits.py)."""
    y_all = df["y"].to_numpy().astype(int)
    models, parts = {}, []
    for name, split in crossfit_folds(df, k=k):
        model = fit(df, split["train"], split["calib"], features, seed)
        pred = predict(model, df[split["test"]])
        models[name] = model
        parts.append(pl.DataFrame({
            "address": df["address"].gather(split["test"]),
            "fold": [name] * len(split["test"]), "y": y_all[split["test"]],
            **{c: pred[c] for c in ("raw", "p", "low", "high")}}))
    oof = pl.concat(parts).sort("address")
    scored = df.join(oof.select("address", "p", "low", "high", "raw"), on="address",
                     how="inner").sort("address")

    def measure(rows: pl.DataFrame) -> dict:
        return evaluate(rows["y"].to_numpy(), {c: rows[c].to_numpy()
                                               for c in ("raw", "p", "low", "high")})

    counts = dict(df.filter(pl.col("y") == 1).group_by("group").len().iter_rows())
    table = [_table_row(g, measure(scored.filter(pl.col("group") == g)))
             for g in sorted(counts) if counts[g] >= max(min_positives, 1)]
    block = {"blocks": k, "pooled": measure(scored), "by_exchange": table,
             "look_alikes": look_alikes(scored, scored["p"].to_numpy())}
    return block, models, oof.drop("y")


def _importance(model: Fitted, df: pl.DataFrame) -> list[dict]:
    """Mean |SHAP| per feature on the given rows, as shares that sum to 1."""
    sv = np.abs(model.detector.shap_values(matrix(df, model.features))).mean(axis=0)
    total = float(sv.sum()) or 1.0
    order = sorted(zip(model.features, sv), key=lambda kv: (-kv[1], kv[0]))
    return [{"feature": f, "importance": round(float(v) / total, 4)} for f, v in order]


def _leak_audit(df: pl.DataFrame, seed: int) -> dict:
    """Fields that must not predict the class: the address itself (its sort rank) and
    the minute and second of its first transfer."""
    frame = df.select("address", "y", pl.col("first_ts").dt.strftime("%Y-%m-%d %H:%M:%S")
                      .alias("first_seen"))
    return audit(frame, "y", ["address"], {"column": "first_seen",
                                           "format": "%Y-%m-%d %H:%M:%S"}, [], seed=seed)


def run(df: pl.DataFrame, seed: int = SEED, min_positives: int = 20,
        blocks: int = 5) -> Result:
    df = df.sort("address")
    y = df["y"].to_numpy().astype(int)
    split = time_split(df)
    final = fit(df, split["train"], split["calib"], FEATURES, seed)
    test = df[split["test"]]
    test_pred = predict(final, test)
    by_time = {"sizes": _sizes(df, split),
               "from": {k: str(df["first_ts"].gather(v).min()) for k, v in split.items()},
               "test": evaluate(y[split["test"]], test_pred),
               "look_alikes": look_alikes(test, test_pred["p"])}
    by_exchange, exchange_models, held_out = _by_exchange(df, FEATURES, seed, hide=False,
                                                          min_positives=min_positives)
    scored = df.join(held_out.select("address", "p"), on="address", how="inner") \
        .sort("address")
    by_exchange["look_alikes"] = look_alikes(scored, scored["p"].to_numpy())
    cross_fit, folds, oof = _cross_fit(df, FEATURES, seed, blocks, min_positives)

    with_labels = FEATURES + LABEL_FEATURES
    ab_model = fit(df, split["train"], split["calib"], with_labels, seed)
    ab_time = evaluate(y[split["test"]], predict(ab_model, test))
    ab_exchange, _, _ = _by_exchange(df, with_labels, seed, hide=True,
                                     min_positives=min_positives)

    by_source = dict(sorted(df.group_by("source").len().iter_rows()))
    by_group = {g: {"positive": int(p), "negative": int(n - p)} for g, n, p in sorted(
        df.group_by("group").agg(pl.len(), pl.col("y").sum()).iter_rows())}
    metrics = {
        "version": VERSION, "chain": df["chain"][0], "seed": seed,
        "backend": final.detector.backend, "features": list(FEATURES),
        "dataset": {"addresses": df.height, "positive": int(y.sum()),
                    "negative": int(len(y) - y.sum()), "by_source": by_source,
                    "by_group": by_group},
        "time_split": by_time,
        "leave_one_exchange_out": by_exchange,
        "cross_fit": cross_fit,
        "ablation_label_features": {
            "features": with_labels,
            "time_split": {k: ab_time[k] for k in ("pr_auc", "roc_auc", "brier", "ece")}
            | {"recall": ab_time["at_0_5"]["recall"], "precision": ab_time["at_0_5"]["precision"]},
            "leave_one_exchange_out": {
                "folds": ab_exchange["folds"],
                "pooled": {k: ab_exchange["pooled"][k]
                           for k in ("n", "n_positive", "pr_auc", "roc_auc", "brier", "ece",
                                     "at_0_5")}}},
        "feature_importance": _importance(final, test),
        "leak_audit": _leak_audit(df, seed),
    }
    return Result(metrics, final, folds, oof, exchange_models)


# ------------------------------------------------------------------ persistence
def save(result: Result, out_dir: Path | str) -> Path:
    """metrics.json (tracked), calibration.json (tracked: the calibration fold's scores)
    and model.pkl (rebuilt by `make model`, not tracked)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(
        json.dumps(result.metrics, indent=1, allow_nan=False) + "\n")
    va = result.final.va
    (out / "calibration.json").write_text(json.dumps(
        {"scores": [float(s) for s in va.s], "labels": [int(v) for v in va.y]}) + "\n")
    with (out / "model.pkl").open("wb") as fh:
        pickle.dump({"detector": result.final.detector, "features": result.final.features}, fh)
    return out / "metrics.json"


def load_model(out_dir: Path | str) -> Fitted:
    out = Path(out_dir)
    with (out / "model.pkl").open("rb") as fh:
        d = pickle.load(fh)
    calib = json.loads((out / "calibration.json").read_text())
    va = VennAbers().fit(calib["scores"], calib["labels"])
    return Fitted(d["detector"], va, d["features"])
