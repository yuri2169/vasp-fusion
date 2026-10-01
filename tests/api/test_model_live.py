"""/api/model serves the measured model when `make model` has written its metrics."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from classifykit import toy_frame  # noqa: E402
from vaspfusion.api import main  # noqa: E402
from vaspfusion.classify.dataset import write_dataset  # noqa: E402
from vaspfusion.classify.report import build_model  # noqa: E402


@pytest.fixture(scope="module")
def model_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("model")
    write_dataset(out / "toy" / "dataset.csv", toy_frame().to_dicts())
    build_model("toy", out, runs=[], trained_at="2026-10-02T00:00:00Z")
    return out


@pytest.fixture
def client(model_dir, monkeypatch):
    monkeypatch.setattr(main, "MODEL_DIR", model_dir)
    return TestClient(main.app)


def test_the_measured_model_is_served_live(client, model_dir):
    r = client.get("/api/model", params={"chain": "toy"})
    assert r.status_code == 200 and r.headers["x-data-source"] == "live"
    body = r.json()
    metrics = json.loads((model_dir / "toy" / "metrics.json").read_text())
    assert body["status"] == "measured" and body["chain"] == "toy"
    assert body["metrics"]["pr_auc"] == metrics["time_split"]["test"]["pr_auc"]
    assert len(body["leave_one_exchange_out"]) == 3 and body["notes"] == metrics["notes"]


def test_a_chain_without_a_model_falls_back_to_the_mock(client):
    r = client.get("/api/model")                      # tron: nothing in this folder
    assert r.status_code == 200 and r.headers["x-data-source"] == "mock"
    assert client.get("/api/model", params={"chain": "../etc"}).status_code == 404


def test_the_abstain_measurement_rides_along_when_it_exists(client, tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from test_abstain import LABELS, ROWS
    from tracekit import CHAIN, ToyLabels, ToyProvider
    from vaspfusion.eval import abstain as A

    monkeypatch.setattr(main, "ABSTAIN_DIR", tmp_path)
    assert client.get("/api/model", params={"chain": "toy"}).json()["abstain"] is None
    wallets = [("W1", "ExA", "r"), ("W2", "ExA", "r"), ("W3", "ExA", "r"), ("W4", "ExB", "r")]
    rows, _ = A.collect(wallets, CHAIN, ToyProvider(ROWS), lambda: ToyLabels(LABELS))
    m = A.measure(rows, "toy")
    (tmp_path / "toy").mkdir()
    (tmp_path / "toy" / "validation.json").write_text(json.dumps(m))
    got = client.get("/api/model", params={"chain": "toy"}).json()["abstain"]
    assert (got["wallets"], got["claims"], got["current_threshold"]) == (4, 4, 0.6)
    assert got["measured_threshold"] is None and got["notes"] == m["notes"]
    bar = next(b for b in got["bars"] if b["threshold"] == 0.6)
    assert bar == {"threshold": 0.6, "claims_answered": 4, "claims_wrong": 1, "risk": 0.25,
                   "risk_upper_bound": bar["risk_upper_bound"], "wallets_named": 3,
                   "wallets_wrong": 0, "wallets_abstained": 1}
    assert all(0 <= p["accuracy"] <= 1 for p in got["risk_coverage"])
    svg = A.risk_coverage_svg(m)
    assert svg.startswith("<svg") and "bar 0.60 in use" in svg
