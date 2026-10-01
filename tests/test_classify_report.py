"""What `make model` writes and what /api/model serves (mechanics on the toy frame)."""
import json

import pytest

from classifykit import toy_frame
from vaspfusion.api import schemas as S
from vaspfusion.classify.dataset import write_dataset
from vaspfusion.classify.explain import FEATURE_NAMES
from vaspfusion.classify.report import build_model, model_info, notes
from vaspfusion.classify.train import run


@pytest.fixture(scope="module")
def metrics():
    return run(toy_frame()).metrics


def test_model_info_is_the_api_contract_filled_from_the_metrics(metrics):
    info = S.ModelInfo.model_validate(model_info({**metrics,
                                                  "trained_at": "2026-10-02T00:00:00Z"}))
    t = metrics["time_split"]["test"]
    assert info.status == "measured" and info.version == "model_v1"
    assert info.split == "by time, and by exchange (leave one exchange out)"
    assert (info.metrics.pr_auc, info.metrics.ece, info.metrics.brier, info.metrics.n_test) == \
        (t["pr_auc"], t["ece"], t["brier"], t["n"])
    assert info.metrics.coverage == t["confident"]["coverage"]
    assert info.metrics.accuracy_when_answering == t["confident"]["accuracy"]
    assert [b.count for b in info.reliability] == [b["count"] for b in t["reliability"]]
    assert {f.feature for f in info.feature_importance} <= set(FEATURE_NAMES.values())
    assert [f.exchange for f in info.leave_one_exchange_out] == ["ExA", "ExB", "ExC"]
    assert info.risk_coverage and info.risk_coverage[-1].coverage == 1.0
    assert 0 <= info.risk_coverage[0].accuracy <= 1
    assert info.trained_at.year == 2026


def test_the_notes_say_what_the_numbers_are_and_are_not(metrics):
    text = " ".join(notes(metrics))
    assert "calibrated" in text and "class mix" in text
    assert "never saw" in text                      # leave one exchange out, in words
    assert "left out of the shipped model" in text  # the label ablation
    assert "rule-set" in text                       # what is still not learned


def test_build_model_writes_every_artefact_and_reruns_to_the_same_files(tmp_path):
    df = toy_frame()
    for name in ("a", "b"):
        write_dataset(tmp_path / name / "toy" / "dataset.csv", df.to_dicts())
        build_model("toy", tmp_path / name, runs=[], trained_at="2026-10-02T00:00:00Z")
    a, b = tmp_path / "a" / "toy", tmp_path / "b" / "toy"
    names = sorted(p.name for p in a.iterdir())
    assert names == ["calibration.json", "dataset.csv", "importance.svg", "metrics.json",
                     "model.pkl", "reliability.svg", "reliability_by_exchange.svg"]
    for name in names:
        if name != "model.pkl":
            assert (a / name).read_bytes() == (b / name).read_bytes(), name
    m = json.loads((a / "metrics.json").read_text())
    assert m["trained_at"] == "2026-10-02T00:00:00Z" and m["notes"]
