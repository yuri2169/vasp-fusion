"""No API test may read or write this machine's stores: every test gets its own desk
store, outbox, officer file, token secret and audit log (a real request in
data/desk.duckdb would change what `GET /api/desk` answers in a test, and a real
officer account would make every test need a login)."""
import pytest

from vaspfusion.api import main, security


@pytest.fixture(autouse=True)
def own_desk(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DESK_DB", tmp_path / "desk.duckdb")
    monkeypatch.setattr(main, "OUTBOX", tmp_path / "outbox")
    monkeypatch.setattr(main, "WATCH_DB", tmp_path / "watch.duckdb")
    monkeypatch.setattr(main, "OFFICERS", tmp_path / "officers.json")
    monkeypatch.setattr(main, "AUDIT_DB", tmp_path / "audit.duckdb")
    monkeypatch.setattr(main, "AUTH_SECRET", tmp_path / "auth_secret")
    monkeypatch.setattr(main, "AUTH", None)
    # These files test the routes with the B1 fixtures standing in for empty stores.
    # test_demo_mode.py turns it off again, which is what a server runs with.
    monkeypatch.setenv("VASPFUSION_DEMO_MODE", "1")
    monkeypatch.delenv("VASPFUSION_AUTH", raising=False)
    monkeypatch.delenv("VASPFUSION_JWT_SECRET", raising=False)
    security.forget()
