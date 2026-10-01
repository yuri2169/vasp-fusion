"""The saved model at runtime: the tracked text dump gives the measured model back, and
one wallet is read and scored with the training set's protocol. No network."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np

from vaspfusion.chains.base import GasEvent, GasList, Transfer, sort_transfers
from vaspfusion.classify.dataset import read_dataset
from vaspfusion.classify.features import FEATURES
from vaspfusion.classify.runtime import Scorer, make_scorer
from vaspfusion.classify.splits import time_split
from vaspfusion.classify.train import evaluate, load_model, predict

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "artifacts" / "model_v1" / "tron"
T0 = datetime(2026, 9, 25, tzinfo=timezone.utc)


def test_the_tracked_text_dump_is_the_model_the_metrics_were_measured_on():
    df = read_dataset(MODEL / "dataset.csv")
    m = json.loads((MODEL / "metrics.json").read_text())
    model = load_model(MODEL)
    assert model.features == FEATURES == m["features"]
    test = time_split(df)["test"]
    pred = predict(model, df[test])
    got = evaluate(df["y"].gather(test).to_numpy(), pred)
    for key in ("pr_auc", "roc_auc", "brier", "ece"):
        assert got[key] == m["time_split"]["test"][key], key
    assert ((pred["low"] <= pred["p"]) & (pred["p"] <= pred["high"])).all()


def test_loading_needs_no_pickle(tmp_path):
    for name in ("model.txt", "model_features.json", "calibration.json"):
        (tmp_path / name).write_bytes((MODEL / name).read_bytes())
    df = read_dataset(MODEL / "dataset.csv").head(50)
    a, b = predict(load_model(tmp_path), df), predict(load_model(MODEL), df)
    assert np.array_equal(a["p"], b["p"])


def tx(n, frm, to, amount, minute):
    return Transfer(chain="tron", tx_hash=f"h{n}", block_time=T0 + timedelta(minutes=minute),
                    from_addr=frm, to_addr=to, asset="USDT", amount=Decimal(amount),
                    amount_usd=Decimal(amount), fee_payer=None, asset_contract="usdt")


class Listings:
    """A provider that answers from hand-written listings and records what was asked."""
    traceable_assets = ("USDT", "TRX")

    def __init__(self, rows, gas=()):
        self.rows, self.gas, self.calls = sort_transfers(rows), list(gas), []

    def transfers(self, address, direction="both", since=None, limit=200, asset=None):
        self.calls.append(("transfers", address, direction, since, limit, asset))
        return [t for t in self.rows if address in (t.from_addr, t.to_addr)
                and t.asset == asset and (since is None or t.block_time >= since)][:limit]

    def gas_events(self, address, since=None, limit=None):
        self.calls.append(("gas", address, since))
        return GasList([e for a, e in self.gas if a == address])


def sweeper():
    """D takes deposits from three senders and sweeps each to C on someone else's energy;
    C keeps what it gets and pays out to many."""
    rows, gas = [], []
    for i in range(3):
        rows += [tx(10 * i, f"U{i}", "D", 500 + i, 100 * i), tx(10 * i + 1, "D", "C", 500 + i, 100 * i + 2)]
        gas.append(("D", GasEvent(time=T0 + timedelta(minutes=100 * i + 1), payer="G",
                                  kind="energy", tx_hash=f"g{i}")))
    rows += [tx(100 + i, "C", f"W{i}", 90, 400 + i) for i in range(8)]
    return Listings(rows, gas)


def test_a_wallet_is_read_with_the_training_protocol_and_scored():
    provider = sweeper()
    s = Scorer(load_model(MODEL), provider).score("D", T0 + timedelta(minutes=5))
    since = T0 + timedelta(minutes=5) - timedelta(days=7)
    assert provider.calls == [("transfers", "D", "both", since, 50, "USDT"), ("gas", "D", since),
                              ("transfers", "C", "both", since, 50, "USDT")]
    assert s.collector == "C" and s.n_rows == 6 and s.complete
    assert s.features["forward_ratio"] == 1.0 and s.features["recipient_forwards_on"] == 0.0
    assert s.features["gas_outside_share"] == 1.0
    assert 0 <= s.low <= s.p <= s.high <= 1 and s.p >= 0.9
    assert len(s.reasons) == 3 and all({"feature", "text", "weight"} == set(r) for r in s.reasons)


def test_a_wallet_that_spends_to_many_scores_low_and_an_empty_one_is_not_scored():
    rows = [tx(1, "U", "W", 1000, 0)] + [tx(10 + i, "W", f"X{i}", 100, 60 * (i + 1)) for i in range(6)]
    model = load_model(MODEL)
    s = Scorer(model, Listings(rows)).score("W", T0)
    assert s.p < 0.5 and s.collector == "X0"
    assert Scorer(model, Listings(rows)).score("NOBODY", T0) is None


def test_only_measured_chains_are_scored_and_a_missing_model_means_no_scorer(tmp_path):
    assert make_scorer("ethereum", fetcher=None) is None
    assert make_scorer("tron", fetcher=None, model_dir=tmp_path) is None
