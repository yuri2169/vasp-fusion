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
