from pathlib import Path

import pytest

from vaspfusion.labels.load import build_labels

FIX = Path(__file__).parent.parent / "fixtures" / "labels"


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory):
    db = tmp_path_factory.mktemp("labels") / "labels.duckdb"
    stats = build_labels(db, FIX / "wa", FIX / "dune.csv")
    return db, stats
