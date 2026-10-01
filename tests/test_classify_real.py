"""The deposit-address model on real data: features of real deposit addresses replayed
from the recorded crawl, and the tracked artefacts of `make model` checked against the
tracked dataset and discovery files. No network."""
import json
from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest

from discoverkit import FixtureLabels
from test_discover_real import CFG, crawl
from vaspfusion.chains.tron import TronProvider
from vaspfusion.classify.dataset import Run, _example, load_runs, read_dataset
from vaspfusion.classify.features import FEATURES
from vaspfusion.classify.score import read_scores
from vaspfusion.classify.splits import exchange_folds, time_split
from vaspfusion.classify.train import evaluate, fit, predict
from vaspfusion.discover.rules import DiscoverConfig

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "artifacts" / "model_v1" / "tron"


@pytest.fixture(scope="module")
def replayed(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("classify")
    mp.delenv("OFFLINE", raising=False)
    mp.setenv("TRONGRID_API_KEY", "")
    mp.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp / "no.env")
    try:
        result, fetcher = crawl(tmp)
        run = Run("tron", "tron", CFG.window_start - timedelta(days=CFG.lookback_days),
                  CFG.candidate_limit, tuple(result.findings))
        provider = TronProvider(fetcher, page_size=50, max_pages=1)
        labels = FixtureLabels("crawl_tron")
        rows = {f.address: _example(f.address, run, run.read(provider, f.address), labels, None,
                                    DiscoverConfig()) for f in result.findings}
        yield result.findings, rows
    finally:
        mp.undo()


def test_ten_real_deposit_addresses_show_the_behaviour_the_model_reads(replayed):
    findings, rows = replayed
    assert len(rows) == 10 and all(rows.values())
    for f in findings:
        r = rows[f.address]
        assert r["forward_ratio"] >= 0.9 and r["top_recipient_share"] >= 0.5, f.address
        assert r["gas_outside_share"] > 0, f.address          # both rules agreed on all ten
        assert r["stable_share"] == 1.0 and r["n_out"] >= 1 and r["n_in"] >= 1
        # the label features see the exchange the rules named, through its other wallets
        assert r["to_exchange_share"] > 0 and r["label_entity"] == f.entity


def test_a_real_coindcx_deposit_address_in_numbers(replayed):
    _, rows = replayed
    r = rows["TTTZH6nWX8tk1b73xHfCJk3x9aBRgWbeEK"]
    assert (r["n_in"], r["n_out"], r["n_senders"], r["n_recipients"]) == (2, 2, 2, 1)
    assert r["forward_ratio"] == 1.0 and r["left_share"] == 0.0
    assert r["dwell_median_s"] == 48 and r["gas_outside_share"] == 0.5
    assert r["to_exchange_share"] == 1.0 and r["gas_from_exchange_share"] == 0.5


# ------------------------------------------------------------------ the tracked artefacts
@pytest.fixture(scope="module")
def tron():
    return (read_dataset(MODEL / "dataset.csv"),
            json.loads((MODEL / "metrics.json").read_text()),
            read_scores(MODEL / "scores.csv"))


def test_the_tracked_metrics_describe_the_tracked_dataset(tron):
    df, m, _ = tron
    d = m["dataset"]
    assert (d["addresses"], d["positive"]) == (df.height, int(df["y"].sum()))
    assert d["by_source"] == dict(sorted(df.group_by("source").len().iter_rows()))
    sizes = m["time_split"]["sizes"]
    assert sizes["train"] + sizes["calib"] + sizes["test"] == df.height
    assert m["cross_fit"]["pooled"]["n"] == df.height
    assert m["seed"] == 26182 and m["backend"] == "lightgbm" and m["features"] == FEATURES


def test_no_real_address_is_in_the_dataset_twice_or_on_two_sides_of_a_split(tron):
    df, _, _ = tron
    assert df["address"].n_unique() == df.height
    s = time_split(df)
    assert not set(s["train"]) & set(s["test"]) and not set(s["calib"]) & set(s["test"])
    assert df["first_ts"].gather(s["train"]).max() <= df["first_ts"].gather(s["test"]).min()
    group = df["group"]
    for exchange, fold in exchange_folds(df):
        assert set(group.gather(fold["test"]).to_list()) == {exchange}
        assert exchange not in set(group.gather(fold["train"]).to_list())
        assert exchange not in set(group.gather(fold["calib"]).to_list())


def test_every_derived_label_has_exactly_one_score_and_no_other_address_has_one(tron):
    df, _, scores = tron
    derived = {f.address: f for run in load_runs(ROOT / "derived") if run.chain == "tron"
               for f in run.findings if f.status == "derived"}
    in_dataset = set(df.filter(pl.col("y") == 1)["address"].to_list())
    assert in_dataset == set(derived)                 # every derived address could be read
    assert {a for a, _ in scores} == set(derived)
    for (address, chain), s in scores.items():
        assert chain == "tron" and s["entity"] == derived[address].entity
        assert s["scored_by"].startswith("cross-fit:block ")
        assert 0 <= s["confidence_low"] <= s["confidence"] <= s["confidence_high"] <= 1
        assert len(json.loads(s["reasons"])) == 3
        assert "not calibrated" not in s["evidence"] and "Model: " in s["evidence"]


def test_the_negatives_are_not_labelled_deposit_addresses_and_not_findings(tron):
    df, _, _ = tron
    fired = {f.address for run in load_runs(ROOT / "derived") for f in run.findings}
    negatives = df.filter(pl.col("y") == 0)
    assert not set(negatives["address"].to_list()) & fired
    assert set(negatives["source"].unique().to_list()) <= {"customer", "labelled:exchange",
                                                           "labelled:sanctioned", "gas_station"}


def test_the_shipped_model_reads_no_label_and_the_label_features_are_only_an_ablation(tron):
    _, m, _ = tron
    assert not {"to_exchange_share", "gas_from_exchange_share"} & set(m["features"])
    ab = m["ablation_label_features"]
    # the positives were chosen by those labels, so with them the model is the rule again...
    assert ab["time_split"]["pr_auc"] >= 0.999
    # ...and it is blind on an exchange whose labels it cannot see
    assert ab["leave_one_exchange_out"]["pooled"]["at_0_5"]["recall"] <= 0.05
    assert m["leak_audit"]["strict_over_gate"] == []


def test_a_real_slice_trains_and_calibrates(tron):
    """A seeded real slice (every 6th address) through the same fit: the model separates
    real deposit addresses from real customers, and its probabilities stay in range."""
    df, _, _ = tron
    part = df.sort("address").gather_every(6)
    s = time_split(part)
    pred = predict(fit(part, s["train"], s["calib"], FEATURES), part[s["test"]])
    m = evaluate(part["y"].gather(s["test"]).to_numpy(), pred)
    assert m["roc_auc"] > 0.85 and m["pr_auc"] > 0.9 and m["brier"] < 0.12
    assert ((pred["low"] <= pred["p"]) & (pred["p"] <= pred["high"])).all()
