"""How the deposit-address dataset is split. Never at random by address.

* By time: the earliest 60% of addresses (by their first transfer in the listing)
  train, the next 20% calibrate, the last 20% test.
* By exchange (leave one exchange out): everything of one exchange's group - its
  deposit addresses, their customers, its own wallets - is the test set. The rest
  trains (earliest 75%) and calibrates (latest 25%). This asks the question that
  matters for an exchange we hold no label for: is its deposit address recognised
  from the behaviour of other exchanges' addresses alone?

Both are built by `eval/splits.make_splits`, whose `verify` rejects an address on
two sides, a test set that starts before training ends, and any row of the
held-out group in training or calibration.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from ..eval.splits import make_splits


def _inputs(df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    if df["address"].n_unique() != df.height:
        raise ValueError("an address is in the dataset more than once: it could land on "
                         "both sides of a split")
    fm = df.select(pl.col("address").alias("entity"))
    labels = df.select(pl.col("address").alias("entity"), pl.col("y").alias("illicit"),
                       pl.col("group").alias("typology"))
    # addresses first seen in the same second are ordered by address, so the order is
    # total and a split never depends on the order of the rows
    order = df.select("address", "first_ts").sort(["first_ts", "address"]) \
        .with_row_index("first_ts_rank")
    first_ts = order.select(pl.col("address").alias("entity"),
                            pl.col("first_ts_rank").cast(pl.Int64).alias("first_ts"))
    return fm, labels, first_ts


def time_split(df: pl.DataFrame,
               fracs: tuple[float, float, float] = (0.6, 0.2, 0.2)) -> dict[str, np.ndarray]:
    """Row indices into `df`: train, calib, test, forward in time."""
    s = make_splits(*_inputs(df), holdout_typologies=[], fracs=fracs)
    return {k: s[k] for k in ("train", "calib", "test")}


def exchange_folds(df: pl.DataFrame, min_positives: int = 20,
                   calib_frac: float = 0.25) -> list[tuple[str, dict[str, np.ndarray]]]:
    """(exchange, {train, calib, test}) for every exchange with enough deposit addresses."""
    fm, labels, first_ts = _inputs(df)
    counts = df.filter(pl.col("y") == 1).group_by("group").len()
    folds = []
    for exchange in sorted(g for g, n in counts.iter_rows() if n >= max(min_positives, 1)):
        s = make_splits(fm, labels, first_ts, holdout_typologies=[exchange],
                        fracs=(1 - calib_frac, calib_frac, 0.0))
        # rounding can leave one last row unassigned: it is the latest, so it calibrates
        folds.append((exchange, {"train": s["train"],
                                 "calib": np.concatenate([s["calib"], s["test"]]),
                                 "test": s["holdout_typology"]}))
    return folds
