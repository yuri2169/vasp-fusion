"""No test may write to this machine's watchlist: `cli demo` seeds the demonstration
watchlist, and without this it would land in data/watch.duckdb."""
import pytest


@pytest.fixture(autouse=True)
def own_watchlist(tmp_path, monkeypatch):
    monkeypatch.setenv("VASPFUSION_WATCH_DB", str(tmp_path / "watch.duckdb"))
