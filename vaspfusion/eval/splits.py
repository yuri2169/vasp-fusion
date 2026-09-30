"""Train / calibrate / test splitting, and the integrity checks that guard it.

Group leakage is the most common silent error in this exact problem, and it is
silent precisely because it makes the numbers better. Three rules, all enforced
by assertions that run in CI rather than by good intentions:

  1. GROUP-AWARE. Every address of one entity lands on one side. Since we
     classify entities rather than addresses this is structural, but the check
     stays because the day someone adds an address-level model it stops being
     free.

  2. TEMPORALLY FORWARD. The test set is strictly later than training. Otherwise
     the model predicts the past from the future, which no deployment can do.

  3. HELD-OUT TYPOLOGIES NEVER APPEAR IN TRAINING. Not one example. This is what
     makes "recall on laundering patterns the model has never seen" a real
     measurement instead of a slogan.

If any of these fails the split is rejected. A rejected split is a bug report,
not a warning to be tuned away.
"""
from __future__ import annotations

import numpy as np
import polars as pl


class SplitViolation(Exception):
    pass


def make_splits(fm: pl.DataFrame, labels: pl.DataFrame, first_ts: pl.DataFrame,
                holdout_typologies: list[str],
                fracs: tuple[float, float, float] = (0.6, 0.2, 0.2),
                seed: int = 20260826) -> dict[str, np.ndarray]:
    """Return index arrays into `fm` for train / calib / test / holdout_typology."""
    df = (fm.select(["entity"])
          .with_row_index("idx")
          .join(labels, on="entity", how="left")
          .join(first_ts, on="entity", how="left"))
    df = df.with_columns([
        pl.col("illicit").fill_null(0).cast(pl.Int8),
        pl.col("typology").fill_null(""),
        pl.col("first_ts").fill_null(pl.col("first_ts").max()),
    ])

    is_holdout = pl.col("typology").is_in(holdout_typologies)
    holdout_idx = df.filter(is_holdout).get_column("idx").to_numpy()
    rest = df.filter(~is_holdout).sort("first_ts")

    n = rest.height
    n_train = int(n * fracs[0])
    n_calib = int(n * fracs[1])
    idx = rest.get_column("idx").to_numpy()
    train_idx = idx[:n_train]
    calib_idx = idx[n_train:n_train + n_calib]
    test_idx = idx[n_train + n_calib:]

    splits = {"train": train_idx, "calib": calib_idx, "test": test_idx,
              "holdout_typology": holdout_idx}
    verify(df, splits, holdout_typologies)
    return splits


def verify(df: pl.DataFrame, splits: dict[str, np.ndarray],
           holdout_typologies: list[str]) -> None:
    """Assert the three rules. Raises rather than warns."""
    seen: set[int] = set()
    for name, idx in splits.items():
        overlap = seen & set(idx.tolist())
        if overlap:
            raise SplitViolation(
                f"{len(overlap)} entities appear in '{name}' and an earlier split. "
                f"An entity on both sides of the boundary is leakage.")
        seen |= set(idx.tolist())

    ts = dict(zip(df.get_column("idx").to_list(), df.get_column("first_ts").to_list()))
    if len(splits["train"]) and len(splits["test"]):
        train_max = max(ts[i] for i in splits["train"].tolist())
        test_min = min(ts[i] for i in splits["test"].tolist())
        if test_min < train_max:
            raise SplitViolation(
                f"Test set begins ({test_min}) before training ends ({train_max}). "
                f"The model would be predicting the past from the future.")

    typ = dict(zip(df.get_column("idx").to_list(), df.get_column("typology").to_list()))
    for name in ("train", "calib"):
        bad = [i for i in splits[name].tolist() if typ.get(i) in holdout_typologies]
        if bad:
            raise SplitViolation(
                f"{len(bad)} held-out-typology entities leaked into '{name}'. "
                f"Held-out means held out - not one example.")


def split_report(df_labels: pl.DataFrame, splits: dict[str, np.ndarray],
                 fm: pl.DataFrame) -> dict:
    ent = fm.get_column("entity").to_list()
    lab = dict(zip(df_labels.get_column("entity").to_list(),
                   df_labels.get_column("illicit").to_list()))
    out = {}
    for name, idx in splits.items():
        ys = [lab.get(ent[i], 0) for i in idx.tolist()]
        out[name] = {"n": len(ys), "n_illicit": int(sum(ys)),
                     "illicit_rate": round(float(np.mean(ys)) if ys else 0.0, 4)}
    return out
