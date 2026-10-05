"""GET /api/cases/{id}/context on the real pipeline, on a recorded demo wallet; no network."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demokit import SPECS, demo_fetcher, demo_label_db  # noqa: E402
from vaspfusion.api import main  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402
from vaspfusion.chains import ChainCache, Fetcher  # noqa: E402

COINDCX = SPECS["tron-coindcx"]["address"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    cache = tmp_path / "cache.duckdb"
    monkeypatch.setattr(main, "LABEL_DB", demo_label_db(tmp_path / "labels.duckdb"))
    monkeypatch.setattr(main, "CASE_DB", tmp_path / "case.duckdb")
    monkeypatch.setattr(main, "AUDIT_DB", tmp_path / "audit.duckdb")
    monkeypatch.setattr(main, "make_fetcher", lambda: demo_fetcher(cache))
    # offline, as the server is for a context it cannot fetch: the cache or nothing
    monkeypatch.setattr(main, "make_verify_fetcher",
                        lambda: Fetcher(ChainCache(cache), None, offline=True))
    monkeypatch.setenv("ETHERSCAN_API_KEY", "test-key")
    monkeypatch.setenv("TRONGRID_API_KEY", "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")
    monkeypatch.delenv("OFFLINE", raising=False)
    monkeypatch.setattr(main, "_CONTEXT_TRACES", {})
    return TestClient(main.app)


@pytest.fixture
def case(client):
    queued = client.post("/api/cases", json={"address": COINDCX}).json()
    return client.get(f"/api/cases/{queued['id']}").json()


def test_the_context_is_the_rest_of_what_the_trace_saw(client, case):
    r = client.get(f"/api/cases/{case['id']}/context")
    assert r.status_code == 200 and r.headers["x-data-source"] == "live"
    ctx = S.CaseContext.model_validate(r.json())
    s = case["trace_summary"]
    assert ctx.transfers == s["transfers_seen"] - s["transfers_followed"] == len(ctx.edges)
    assert ctx.recorded and not ctx.truncated
    # and the case is as it was
    assert client.get(f"/api/cases/{case['id']}").json() == case


def test_one_wallet_and_a_limit(client, case):
    whole = client.get(f"/api/cases/{case['id']}/context").json()
    mine = client.get(f"/api/cases/{case['id']}/context", params={"wallet": COINDCX}).json()
    assert mine["wallet"] == COINDCX and 0 < mine["transfers"] <= whole["transfers"]
    assert all(COINDCX in (e["source"], e["target"]) for e in mine["edges"])
    cut = client.get(f"/api/cases/{case['id']}/context", params={"limit": 5}).json()
    assert (len(cut["edges"]), cut["truncated"], cut["transfers"]) == (5, True, whole["transfers"])


def test_a_wallet_the_trace_did_not_read_is_not_recorded_when_the_server_is_offline(
        client, case, monkeypatch):
    labelled = next(n["id"] for n in case["graph"]["nodes"] if n["label"] is not None)
    # a labelled wallet is where the trail ends, so its listing was never read
    monkeypatch.setattr(main, "make_fetcher", main.make_verify_fetcher)
    r = client.get(f"/api/cases/{case['id']}/context", params={"wallet": labelled})
    assert r.status_code == 200
    body = r.json()
    assert body["recorded"] is False and body["edges"] == [] and body["live"] is False
    assert "not recorded" in body["reason"] and body["text"] == body["reason"]


def test_refusals(client, case):
    assert client.get(f"/api/cases/{case['id']}/context",
                      params={"wallet": "TNotAWalletOfThisCase"}).status_code == 404
    assert client.get("/api/cases/c-nothing/context").status_code == 404


def test_reading_context_is_logged(client, case):
    client.get(f"/api/cases/{case['id']}/context", params={"wallet": COINDCX})
    rows = client.get("/api/audit").json()["items"]
    row = next(r for r in rows if r["action"] == "case.context")
    assert row["target"] == case["id"] and row["detail"] == {"wallet": COINDCX}
