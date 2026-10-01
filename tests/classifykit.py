"""A toy dataset frame for the mechanics of training, calibration and scoring.

The numbers are drawn, not measured: they only make the two classes separable so the
plumbing can be tested fast. Nothing here is ever reported; the real dataset is
covered by tests/test_classify_real.py.
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import polars as pl

from vaspfusion.classify.features import FEATURES, LABEL_FEATURES

T0 = datetime(2026, 9, 17, tzinfo=timezone.utc)
GROUPS = ("ExA", "ExB", "ExC")


def toy_frame(n: int = 240, seed: int = 5) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        y = i % 2
        group = GROUPS[(i // 2) % 3]
        row = {"address": f"{'P' if y else 'C'}{i:04d}", "chain": "toy", "y": y, "group": group,
               "source": "derived" if y else "customer", "run": "toy",
               "first_ts": T0 + timedelta(minutes=int(rng.integers(0, 20_000))),
               "n_rows": 6, "complete": 1, "label_entity": group if y else None}
        for f in FEATURES:
            row[f] = float(rng.normal(0, 1))
        # deposit addresses forward nearly everything on someone else's gas; one in ten
        # customers looks the same
        looks_like = y == 1 or rng.random() < 0.1
        row["forward_ratio"] = float(np.clip(rng.normal(0.97 if looks_like else 0.5, 0.05), 0, 1))
        row["gas_outside_share"] = float(rng.random() < (0.9 if looks_like else 0.15))
        if rng.random() < 0.1:
            row["dwell_median_s"] = None
        row["to_exchange_share"] = 1.0 if y else 0.0
        row["gas_from_exchange_share"] = 1.0 if y and i % 4 else 0.0
        rows.append(row)
    schema = {"first_ts": pl.Datetime("us", "UTC"), "y": pl.Int8, "label_entity": pl.String,
              **{f: pl.Float64 for f in FEATURES + LABEL_FEATURES}}
    return pl.DataFrame(rows, schema_overrides=schema).sort("address")
