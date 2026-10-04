"""No test may write to this machine's watchlist or its SAHYOG intake key: `cli demo`
seeds the demonstration watchlist and creates the simulator's key, and without this they
would land in data/watch.duckdb and data/sahyog_api_key."""
import pytest


@pytest.fixture(autouse=True)
def own_watchlist(tmp_path, monkeypatch):
    monkeypatch.setenv("VASPFUSION_WATCH_DB", str(tmp_path / "watch.duckdb"))
    monkeypatch.setenv("VASPFUSION_SAHYOG_KEY_FILE", str(tmp_path / "sahyog_api_key"))
