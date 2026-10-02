"""`make reproduce` compares regenerated artifacts with what git holds. The one thing
allowed to differ is the time of the run."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import reproduce as R  # noqa: E402

METRICS = {"version": "model_v1", "trained_at": "2026-10-02T00:00:00Z",
           "by_time": {"pr_auc": 0.955, "n": 294}, "folds": [{"exchange": "OKX", "recall": 0.999}]}


def blob(d) -> bytes:
    return (json.dumps(d, indent=1) + "\n").encode()


def test_identical_bytes_are_the_same():
    assert R.classify("artifacts/model_v1/tron/metrics.json", blob(METRICS), blob(METRICS)) == "same"


def test_only_the_time_of_the_run_may_differ():
    later = {**METRICS, "trained_at": "2026-10-03T11:22:33Z"}
    assert R.classify("artifacts/model_v1/tron/metrics.json", blob(METRICS), blob(later)) == \
        "only_timestamp"


def test_a_changed_figure_is_a_change_even_beside_a_new_timestamp():
    later = {**METRICS, "trained_at": "2026-10-03T11:22:33Z",
             "by_time": {"pr_auc": 0.956, "n": 294}}
    assert R.classify("artifacts/model_v1/tron/metrics.json", blob(METRICS), blob(later)) == "changed"
    deep = {**METRICS, "folds": [{"exchange": "OKX", "recall": 0.998}]}
    assert R.classify("x.json", blob(METRICS), blob(deep)) == "changed"


def test_a_timestamp_is_only_forgiven_in_json():
    assert R.classify("derived/tron.csv", b"a,trained_at\n1,2\n", b"a,trained_at\n1,3\n") == "changed"
    assert R.classify("x.json", b"not json", b"not json either") == "changed"


def test_a_file_that_appeared_or_vanished_is_a_change():
    assert R.classify("mocks/desk.json", blob(METRICS), None) == "changed"
    assert R.classify("mocks/desk.json", None, blob(METRICS)) == "changed"


def test_every_tracked_artifact_folder_is_compared():
    for needed in ("artifacts", "derived", "mocks", "docs/openapi.json", "tests/golden"):
        assert needed in R.ARTIFACTS
    assert R.VOLATILE == ("trained_at",)


def test_the_research_folder_is_found_from_a_worktree_too():
    found = R.research_dir()
    assert found is None or (found.name == "data" and found.parent.name == "research")
