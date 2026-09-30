"""Unsupervised detection: the answer to "what about patterns you never labelled?"

ISOLATION FOREST gives a per-entity novelty score. Linear time, no distance-metric
assumption, robust in high dimensions - all three matter when the feature space is
40 engineered dimensions plus 64 embedding dimensions.

HDBSCAN groups entities into behavioural archetypes nobody labelled, and - the
part that actually matters - explicitly labels points that belong to no cluster
as noise. An outlier IS the noise label, which is why this is the right algorithm
and k-means is not: k-means would force every entity into some cluster and has to
be told k in advance. HDBSCAN ships inside scikit-learn >= 1.3, so it costs no
extra dependency.

Together these satisfy the PS's "cluster entities" requirement at the BEHAVIOURAL
level, which is a different claim from the deterministic address clustering in
graph/resolve.py. Both are real and the write-up should name both (§16.1 row 7).

SCALING matters here in a way it does not for the trees: both algorithms are
distance-based, so features go through RobustScaler first - robust because our
targets ARE the outliers and a standard scaler would let them define the scale.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler


class NoveltyDetector:
    def __init__(self, seed: int = 20260826, contamination: float = 0.05):
        self.seed = seed
        self.contamination = contamination
        self.scaler: RobustScaler | None = None
        self.iso: IsolationForest | None = None
        self.cluster_labels_: np.ndarray | None = None
        self.cluster_stats_: dict = {}

    def fit(self, X: np.ndarray) -> "NoveltyDetector":
        self.scaler = RobustScaler().fit(X)
        Xs = np.nan_to_num(self.scaler.transform(X), nan=0.0, posinf=0.0, neginf=0.0)
        self.iso = IsolationForest(
            n_estimators=200, contamination=self.contamination,
            max_samples=min(8192, len(Xs)), random_state=self.seed, n_jobs=-1).fit(Xs)
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        """Novelty in [0,1]; 1 = most anomalous.

        IsolationForest's decision_function is higher-is-more-normal, so it is
        inverted and min-max normalised to sit on the same scale as the
        supervised probability before fusion.
        """
        Xs = np.nan_to_num(self.scaler.transform(X), nan=0.0, posinf=0.0, neginf=0.0)
        raw = -self.iso.decision_function(Xs)
        lo, hi = np.percentile(raw, [1, 99])
        if hi - lo < 1e-9:
            return np.zeros(len(raw), dtype=np.float32)
        return np.clip((raw - lo) / (hi - lo), 0, 1).astype(np.float32)

    def cluster(self, X: np.ndarray, min_cluster_size: int = 25) -> np.ndarray:
        """Behavioural archetypes. -1 means "in no cluster", i.e. an outlier."""
        from sklearn.cluster import HDBSCAN
        Xs = np.nan_to_num(self.scaler.transform(X), nan=0.0, posinf=0.0, neginf=0.0)
        # Cluster in a reduced space: HDBSCAN's density estimates degrade badly in
        # ~128 dimensions, and PCA first is the standard remedy.
        if Xs.shape[1] > 24:
            from sklearn.decomposition import PCA
            Xs = PCA(n_components=24, random_state=self.seed).fit_transform(Xs)
        hdb = HDBSCAN(min_cluster_size=min_cluster_size, min_samples=10,
                      cluster_selection_method="eom")
        labels = hdb.fit_predict(Xs)
        self.cluster_labels_ = labels
        uniq, counts = np.unique(labels[labels >= 0], return_counts=True)
        self.cluster_stats_ = {
            "n_clusters": int(len(uniq)),
            "n_noise": int((labels == -1).sum()),
            "noise_fraction": float((labels == -1).mean()),
            "sizes": {int(u): int(c) for u, c in zip(uniq, counts)},
        }
        return labels

    def save(self, path) -> None:
        import pickle
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("wb") as fh:
            pickle.dump({"scaler": self.scaler, "iso": self.iso, "seed": self.seed,
                         "contamination": self.contamination}, fh)

    @classmethod
    def load(cls, path) -> "NoveltyDetector":
        import pickle
        with open(path, "rb") as fh:
            d = pickle.load(fh)
        o = cls(seed=d["seed"], contamination=d["contamination"])
        o.scaler, o.iso = d["scaler"], d["iso"]
        return o
