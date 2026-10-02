"""Replay of recorded live responses (scripts/record_chain_fixtures.py). No network."""
import pytest

from chainfix import FixtureTransport
from vaspfusion.chains.cache import ChainCache, Fetcher


@pytest.fixture
def fixture_fetcher(tmp_path, monkeypatch):
    """fixture_fetcher('tron_usdt') -> Fetcher replaying that fixture into a fresh cache.
    Keys are blanked so providers behave the same on every machine."""
    monkeypatch.delenv("OFFLINE", raising=False)
    for k in ("TRONGRID_API_KEY", "ETHERSCAN_API_KEY"):
        monkeypatch.setenv(k, "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")
    # btc_pages.json was recorded from mempool.space (B2); the backend is part of the URL
    monkeypatch.setenv("VASPFUSION_BTC_API", "mempool.space")

    def make(*names, offline=False):
        return Fetcher(ChainCache(tmp_path / "cache.duckdb"), FixtureTransport(*names),
                       offline=offline, sleep=lambda s: None)
    return make
