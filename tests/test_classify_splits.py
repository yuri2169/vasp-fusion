"""Splits of the deposit-address dataset: by time and by exchange, never at random."""
from datetime import datetime, timedelta, timezone

import polars as pl
import pytest

from vaspfusion.classify.splits import exchange_folds, time_split

T0 = datetime(2026, 9, 17, tzinfo=timezone.utc)


def frame(rows):
    """rows: (address, y, group, minutes after T0)"""
    return pl.DataFrame({"address": [r[0] for r in rows], "y": [r[1] for r in rows],
                         "group": [r[2] for r in rows],
                         "first_ts": [T0 + timedelta(minutes=r[3]) for r in rows]},
                        schema_overrides={"first_ts": pl.Datetime("us", "UTC")})


def dataset(n=40):
    rows = []
    for i in range(n):
        g = ("ExA", "ExB", "ExC")[i % 3]
        rows.append((f"P{i:02d}", 1, g, i * 7 % 50))
        rows.append((f"C{i:02d}", 0, g, i * 11 % 50))
    rows += [(f"L{i}", 0, "other", i) for i in range(6)]
    return frame(rows)


def addresses(df, idx):
    return set(df["address"].gather(idx).to_list())


def test_the_time_split_trains_on_the_past_and_tests_on_the_future():
    df = dataset()
    s = time_split(df)
    assert len(s["train"]) + len(s["calib"]) + len(s["test"]) == df.height
    assert not (set(s["train"]) & set(s["calib"]) or set(s["train"]) & set(s["test"])
                or set(s["calib"]) & set(s["test"]))
    ts = df["first_ts"]
    assert ts.gather(s["train"]).max() <= ts.gather(s["calib"]).min()
    assert ts.gather(s["calib"]).max() <= ts.gather(s["test"]).min()
    assert len(s["train"]) == int(df.height * 0.6) and len(s["calib"]) == int(df.height * 0.2)


def test_addresses_first_seen_in_the_same_second_split_the_same_way_every_time():
    df = dataset()
    shuffled = df.sample(fraction=1.0, shuffle=True, seed=3)
    a, b = time_split(df), time_split(shuffled)
    for part in ("train", "calib", "test"):
        assert addresses(df, a[part]) == addresses(shuffled, b[part])


def test_an_exchange_fold_holds_out_everything_of_that_exchange():
    df = dataset()
    folds = dict(exchange_folds(df, min_positives=5))
    assert sorted(folds) == ["ExA", "ExB", "ExC"]
    s = folds["ExB"]
    group = df["group"]
    assert set(group.gather(s["test"]).to_list()) == {"ExB"}
    assert len(s["test"]) == df.filter(pl.col("group") == "ExB").height
    assert "ExB" not in set(group.gather(s["train"]).to_list())
    assert "ExB" not in set(group.gather(s["calib"]).to_list())
    assert len(s["train"]) + len(s["calib"]) + len(s["test"]) == df.height
    assert df["first_ts"].gather(s["train"]).max() <= df["first_ts"].gather(s["calib"]).min()
    assert set(df["y"].gather(s["test"]).to_list()) == {0, 1}


def test_only_exchanges_with_enough_deposit_addresses_get_a_fold():
    df = pl.concat([dataset(), frame([("Q1", 1, "Tiny", 3), ("Q2", 0, "Tiny", 4)])])
    assert [g for g, _ in exchange_folds(df, min_positives=5)] == ["ExA", "ExB", "ExC"]
    assert "other" not in [g for g, _ in exchange_folds(df, min_positives=0)]


def test_one_address_twice_is_refused():
    df = pl.concat([dataset(), frame([("P00", 0, "ExB", 9)])])
    with pytest.raises(ValueError, match="more than once"):
        time_split(df)
    with pytest.raises(ValueError, match="more than once"):
        exchange_folds(df)
