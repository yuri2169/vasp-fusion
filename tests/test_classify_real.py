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
