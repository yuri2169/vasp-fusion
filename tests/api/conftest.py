"""No API test may read or write this machine's request desk: every test gets its own
desk store and outbox (a real request in data/desk.duckdb would otherwise change what
`GET /api/desk` answers in a test)."""
import pytest

from vaspfusion.api import main


@pytest.fixture(autouse=True)
def own_desk(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DESK_DB", tmp_path / "desk.duckdb")
    monkeypatch.setattr(main, "OUTBOX", tmp_path / "outbox")
