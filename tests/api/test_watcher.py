"""The background watcher on the real pipeline, with recorded chain responses that
change between two checks: first the watched wallet's page as it would have been before
it paid anyone (its outgoing transfers left out of the recorded page), then the page as
recorded. Everything else is the recording, untouched. No network."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demokit import SPECS, DemoTransport  # noqa: E402
from demokit import demo_label_db  # noqa: E402
from vaspfusion import watcher  # noqa: E402
from vaspfusion.api import main  # noqa: E402
from vaspfusion.chains.cache import ChainCache, Fetcher  # noqa: E402

T0 = datetime(2026, 10, 8, 6, 0, 0, tzinfo=timezone.utc)


class Changing(DemoTransport):
    """The recording, with one wallet's outgoing transfers held back until `moved`."""

    def __init__(self, wallet: str):
        super().__init__(*SPECS)
        self.wallet, self.moved = wallet, False

    def get(self, url, params, headers):
        status, raw = super().get(url, params, headers)
        if self.moved or f"/accounts/{self.wallet}/" not in url:
            return status, raw
        body = json.loads(raw)
        body["data"] = [row for row in body.get("data", [])
                        if row.get("from") != self.wallet
                        and (row.get("raw_data") is None or row.get("to") == self.wallet)]
        return status, json.dumps(body).encode()


def served(tmp_path, monkeypatch, wallet: str) -> tuple[TestClient, Changing]:
    chain = Changing(wallet)
    monkeypatch.setattr(main, "LABEL_DB", demo_label_db(tmp_path / "labels.duckdb"))
    monkeypatch.setattr(main, "CASE_DB", tmp_path / "case.duckdb")
    monkeypatch.setattr(main, "make_fetcher", lambda: Fetcher(
        ChainCache(tmp_path / "cache.duckdb"), chain, sleep=lambda s: None))
    monkeypatch.setenv("ETHERSCAN_API_KEY", "test-key")
    monkeypatch.setenv("TRONGRID_API_KEY", "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")
    monkeypatch.delenv("OFFLINE", raising=False)
    return TestClient(main.app), chain


def watch(client, wallet: str) -> dict:
    assert client.post("/api/cases", json={"address": wallet}).status_code == 202
    made = client.post("/api/watchlist", json={"address": wallet})
    assert made.status_code == 201, made.text
    return made.json()


def test_the_watcher_is_off_unless_an_interval_is_set(tmp_path, monkeypatch):
    client, _ = served(tmp_path, monkeypatch, SPECS["tron-coindcx"]["address"])
    watch(client, SPECS["tron-coindcx"]["address"])
    assert watcher.every() == 0 and main.watch_tick(T0) == []
    state = client.get("/api/watchlist").json()["watcher"]
    assert state["enabled"] is False and "checked when you ask" in state["says"]


def test_a_scheduled_check_finds_a_new_transfer_and_a_new_exchange_with_the_time(
        tmp_path, monkeypatch):
    wallet = SPECS["tron-coindcx"]["address"]
    client, chain = served(tmp_path, monkeypatch, wallet)
    item = watch(client, wallet)
    assert item["state"] == "unchanged" and item["changes"] == []
    monkeypatch.setenv("VASPFUSION_WATCH_INTERVAL", "600")

    # the first scheduled check: the chain says what it said before
    assert main.watch_tick(T0) == [item["id"]]
    listed, = client.get("/api/watchlist").json()["items"]
    assert listed["state"] == "unchanged" and listed["auto_checked_at"] == "2026-10-08T06:00:00Z"
    # not due again until the interval has passed
    assert main.watch_tick(T0 + timedelta(seconds=599)) == []

    chain.moved = True          # the wallet pays out; nobody touches the tool
    assert main.watch_tick(T0 + timedelta(seconds=600)) == [item["id"]]
    listed, = client.get("/api/watchlist").json()["items"]
    kinds = {c["kind"]: c for c in listed["changes"]}
    assert listed["state"] == "changed"
    assert "new transfer" in kinds["new_activity"]["text"]
    assert "CoinDCX" in kinds["new_exchange"]["text"]
    # each change carries the time of the trace that found it
    assert all(c["at"] == listed["last_checked_at"] for c in listed["changes"])
    alerts = client.get("/api/dashboard").json()["recent_alerts"]
    assert any("Watched wallet: New exchange contact: CoinDCX" in a["text"] for a in alerts)


def test_a_scheduled_check_raises_the_risk_class_when_the_wallet_pays_a_listed_address(
        tmp_path, monkeypatch):
    wallet = SPECS["tron-ofac"]["address"]
    client, chain = served(tmp_path, monkeypatch, wallet)
    item = watch(client, wallet)
    assert item["risk_class"] == "low"
    monkeypatch.setenv("VASPFUSION_WATCH_INTERVAL", "60")
    chain.moved = True
    assert main.watch_tick(T0) == [item["id"]]
    listed, = client.get("/api/watchlist").json()["items"]
    rise = next(c for c in listed["changes"] if c["kind"] == "risk_raised")
    assert listed["risk_class"] == "severe" and rise["severity"] == "high"
    assert "rose from Low to Severe" in rise["text"] and rise["at"] == listed["last_checked_at"]


def test_a_manual_check_also_reads_the_chain_afresh(tmp_path, monkeypatch):
    wallet = SPECS["tron-coindcx"]["address"]
    client, chain = served(tmp_path, monkeypatch, wallet)
    item = watch(client, wallet)
    chain.moved = True
    assert client.post(f"/api/watchlist/{item['id']}/check").status_code == 202
    listed, = client.get("/api/watchlist").json()["items"]
    assert listed["state"] == "changed"


def test_the_wallets_longest_unchecked_come_first_and_a_fresh_one_waits():
    entries = [{"id": "a", "auto_checked_at": "2026-10-08T05:50:00Z"},
               {"id": "b"}, {"id": "c", "auto_checked_at": "2026-10-08T05:59:30Z"}]
    assert [e["id"] for e in watcher.due(entries, T0, 60)] == ["b", "a"]
    assert watcher.due(entries, T0, 0) == []


def test_the_watcher_thread_keeps_going_after_a_tick_that_fails():
    import threading
    seen, done = [], threading.Event()

    def tick():
        seen.append(1)
        if len(seen) == 1:
            raise RuntimeError("the store was busy")
        done.set()

    w = watcher.Watcher(tick, 4)
    w.pause = 0.01
    w.start()
    assert done.wait(5)
    w.stop()
    w.join(5)
    assert not w.is_alive() and w.last_run_at is not None
