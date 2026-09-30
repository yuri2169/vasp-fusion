"""The supervised classifier - the PS's "working model, not just rules".

MODEL CHOICE. Gradient-boosted trees on tabular data, for three reasons that hold
up under questioning: they are best-in-class on this shape of problem, they train
in minutes on CPU with no GPU anywhere in the stack, and SHAP is EXACT for trees
rather than approximated. Weber et al. (2019) found tree ensembles outperformed a
GCN on precisely this task (illicit-class F1 on Elliptic), which is why the
fashionable architecture is an ablation here and not the shipped model.

BACKENDS. LightGBM is the reference. Where its OpenMP runtime is unavailable -
macOS without libomp, most notably - we fall back to scikit-learn's
HistGradientBoosting, which is the same histogram-based algorithm (scikit-learn's
own docs credit LightGBM as its inspiration) and which shap.TreeExplainer also
explains exactly. The backend actually used is recorded in the model manifest, so
a number can always be traced to the thing that produced it.

CLASS IMBALANCE is handled with class weights, never SMOTE. Synthesising minority
entities on a graph problem invents actors that do not exist and corrupts every
topology feature they touch (roadmap §6.4 step 12).
"""
from __future__ import annotations

import numpy as np


def _lightgbm_available() -> bool:
    try:
        import lightgbm  # noqa: F401
        return True
    except Exception:
        return False


class SupervisedDetector:
    def __init__(self, seed: int = 20260826, backend: str = "auto"):
        self.seed = seed
        self.backend = backend if backend != "auto" else (
            "lightgbm" if _lightgbm_available() else "sklearn_histgb")
        self.model = None
        self.feature_names: list[str] = []
        self._explainer = None

    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: list[str],
            n_estimators: int = 300) -> "SupervisedDetector":
        self.feature_names = list(feature_names)
        pos = max(1, int(y.sum()))
        neg = max(1, int(len(y) - pos))
        scale = neg / pos

        if self.backend == "lightgbm":
            import lightgbm as lgb
            self.model = lgb.LGBMClassifier(
                n_estimators=n_estimators, num_leaves=63, learning_rate=0.06,
                min_child_samples=30, subsample=0.85, subsample_freq=1,
                colsample_bytree=0.8, reg_lambda=1.0,
                scale_pos_weight=scale, random_state=self.seed,
                n_jobs=-1, verbose=-1)
            self.model.fit(X, y, eval_set=[(X, y)],
                           callbacks=[__import__("lightgbm").early_stopping(20, verbose=False)])
        else:
            from sklearn.ensemble import HistGradientBoostingClassifier
            # class_weight="balanced" is the sklearn equivalent of scale_pos_weight.
            self.model = HistGradientBoostingClassifier(
                max_iter=n_estimators, max_leaf_nodes=63, learning_rate=0.06,
                min_samples_leaf=30, l2_regularization=1.0,
                class_weight="balanced", random_state=self.seed,
                # Stop when held-out loss stops improving. Without this the model
                # drives training PR-AUC to 1.0 and learns the training fold.
                early_stopping=True, validation_fraction=0.15, n_iter_no_change=20)
            self.model.fit(X, y)
        return self

    def fit_weighted(self, X: np.ndarray, y: np.ndarray, w: np.ndarray,
                     feature_names: list[str],
                     n_estimators: int = 300) -> "SupervisedDetector":
        """Same model, per-example weights instead of class weights.

        Used by the PU learner, where an unlabelled example enters as both
        classes with weights that sum to one. Class weighting is meaningless
        there - every row already carries its own - so it is switched off rather
        than compounded on top.
        """
        self.feature_names = list(feature_names)
        if self.backend == "lightgbm":
            import lightgbm as lgb
            self.model = lgb.LGBMClassifier(
                n_estimators=n_estimators, num_leaves=63, learning_rate=0.06,
                min_child_samples=30, subsample=0.85, subsample_freq=1,
                colsample_bytree=0.8, reg_lambda=1.0,
                random_state=self.seed, n_jobs=-1, verbose=-1)
            self.model.fit(X, y, sample_weight=w)
        else:
            from sklearn.ensemble import HistGradientBoostingClassifier
            self.model = HistGradientBoostingClassifier(
                max_iter=n_estimators, max_leaf_nodes=63, learning_rate=0.06,
                min_samples_leaf=30, l2_regularization=1.0,
                random_state=self.seed,
                early_stopping=True, validation_fraction=0.15, n_iter_no_change=20)
            self.model.fit(X, y, sample_weight=w)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        p = self.model.predict_proba(X)
        return p[:, 1] if p.ndim == 2 else p

    def shap_values(self, X: np.ndarray) -> np.ndarray:
        """Exact per-feature attributions for tree ensembles.

        TreeExplainer only - KernelExplainer is ~100x slower and approximate, and
        we only ever need this for the handful of alerts actually on screen.
        """
        import shap
        if self._explainer is None:
            self._explainer = shap.TreeExplainer(self.model)
        sv = self._explainer.shap_values(X)
        sv = np.asarray(sv)
        if sv.ndim == 3:                     # (n, features, classes)
            sv = sv[:, :, -1]
        return sv

    def feature_importance(self, X: np.ndarray | None = None,
                           sample: int = 2000) -> dict[str, float]:
        """Global importance, normalised to sum to 1.

        LightGBM exposes split-count importances directly. HistGradientBoosting
        exposes none, so we fall back to mean |SHAP| over a sample - which is a
        better measure regardless, since it reflects effect on the prediction
        rather than how often a feature was split on.
        """
        m = self.model
        if hasattr(m, "feature_importances_"):
            imp = np.asarray(m.feature_importances_, dtype=float)
        elif X is not None and len(X):
            idx = np.random.default_rng(self.seed).choice(
                len(X), size=min(sample, len(X)), replace=False)
            imp = np.abs(self.shap_values(X[idx])).mean(axis=0)
        else:
            return {}
        total = imp.sum() or 1.0
        return {n: float(v / total) for n, v in zip(self.feature_names, imp)}

    # -- persistence ------------------------------------------------------
    def save(self, path) -> None:
        import pickle
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("wb") as fh:
            pickle.dump({"backend": self.backend, "model": self.model,
                         "feature_names": self.feature_names, "seed": self.seed}, fh)

    @classmethod
    def load(cls, path) -> "SupervisedDetector":
        import pickle
        with open(path, "rb") as fh:
            d = pickle.load(fh)
        o = cls(seed=d["seed"], backend=d["backend"])
        o.model = d["model"]
        o.feature_names = d["feature_names"]
        return o
