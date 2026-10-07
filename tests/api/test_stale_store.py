"""A case store written by an earlier version: cases that lack the fields added since
(or hold null for them) list and open like any other, and one record that cannot be
read does not take the list down. Replays a recorded demo wallet; no network."""
import json
import sys
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demokit import demo_fetcher, demo_label_db, run_demo  # noqa: E402
from vaspfusion import provenance as P  # noqa: E402
from vaspfusion.api import main  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402
from vaspfusion.chains.cache import ChainCache, Fetcher  # noqa: E402
from vaspfusion.store.cases import ADDED_SINCE, CaseStore  # noqa: E402


def as_first_stored(case: dict, case_id: str, *, null: bool) -> dict:
    """The case as a version before `ADDED_SINCE` would have stored it: those fields
    absent (or null), and the content digest taken from that."""
    old = {k: v for k, v in case.items() if k not in ADDED_SINCE}
    if null:
        old.update(dict.fromkeys(ADDED_SINCE))
    old["id"] = case_id
    old["provenance"] = {**case["provenance"], "git_commit": "0" * 40,     # earlier code
                         "content_sha256": P.content_sha256(old)}
    return old


@pytest.fixture
def client(tmp_path, monkeypatch):
    cache = tmp_path / "cache.duckdb"
    monkeypatch.setattr(main, "LABEL_DB", demo_label_db(tmp_path / "labels.duckdb"))
    monkeypatch.setattr(main, "CASE_DB", tmp_path / "case.duckdb")
    monkeypatch.setattr(main, "make_fetcher", lambda: demo_fetcher(cache))
    monkeypatch.setattr(main, "make_verify_fetcher",
                        lambda: Fetcher(ChainCache(cache), None, offline=True))
    monkeypatch.setenv("ETHERSCAN_API_KEY", "test-key")
    monkeypatch.setenv("TRONGRID_API_KEY", "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")
    monkeypatch.delenv("OFFLINE", raising=False)
    monkeypatch.setenv("VASPFUSION_DEMO_MODE", "0")       # the stored cases only
    case = run_demo("tron-coindcx", cache)
    store = CaseStore(tmp_path / "case.duckdb")
    store.save(case)
    store.save(as_first_stored(case, "old-absent", null=False))
    store.save(as_first_stored(case, "old-null", null=True))
    return TestClient(main.app)


def put_raw(tmp_path, case_id: str, detail: str, minute: int = 0) -> None:
    """A row as it lies in the file, whatever its `detail` holds."""
    with duckdb.connect(str(tmp_path / "case.duckdb")) as con:
        con.execute("INSERT INTO cases VALUES (?, ?, 'tron', 'done', 'ATTRIBUTED', ?, ?)",
                    [case_id, "TBrokenRecordAddress", f"2026-09-30 10:{minute:02d}:00", detail])


OLD = ("old-absent", "old-null")


def test_cases_stored_before_the_newer_fields_are_listed(client):
    r = client.get("/api/cases")
    assert r.status_code == 200
    items = {c["id"]: c for c in S.CaseList.model_validate(r.json()).model_dump()["items"]}
    assert set(items) == {"tron-coindcx", *OLD}
    for cid in OLD:
        assert items[cid]["threats"] == [] and items[cid]["screening"] is None
        assert (items[cid]["outcome"], items[cid]["top_vasp"]) == ("ATTRIBUTED", "CoinDCX")
        # risk is worked out when a case is read, so an old case has it as well
        assert items[cid]["risk_score"] == items["tron-coindcx"]["risk_score"]
    assert {c["id"] for c in client.get("/api/cases?threat=any").json()["items"]}.isdisjoint(OLD)


@pytest.mark.parametrize("cid", OLD)
def test_a_case_stored_before_the_newer_fields_opens(client, cid):
    r = client.get(f"/api/cases/{cid}")
    assert r.status_code == 200
    case = S.CaseDetail.model_validate(r.json()).model_dump()
    assert (case["threats"], case["crossings"], case["tx_chains"]) == ([], [], {})
    assert case["chains"] == ["tron"]            # it was followed on its own chain only
    assert case["trace_summary"] is None and case["screening"] is None
    assert case["risk"] is not None
    assert len(case["candidates"]) == len(client.get("/api/cases/tron-coindcx").json()["candidates"])


@pytest.mark.parametrize("cid", OLD)
def test_every_route_that_returns_a_case_answers_for_an_old_one(client, cid):
    address = client.get(f"/api/cases/{cid}").json()["address"]
    for path in (f"/api/cases/{cid}/pdf", f"/api/cases/{cid}/receipt",
                 f"/api/cases/{cid}/context", f"/api/wallets/tron/{address}",
                 "/api/dashboard", "/api/watchlist"):
        assert client.get(path).status_code == 200, path


@pytest.mark.parametrize("cid", OLD)
def test_an_old_case_is_verified_against_the_record_as_it_was_stored(client, cid):
    """The fields filled in when a case is read are not part of what was stored, so they
    must not make its content digest look edited."""
    out = client.post(f"/api/cases/{cid}/verify").json()
    assert out["matches"] is True, out
    checks = {c["name"]: c["result"] for c in out["checks"]}
    assert (checks["stored_case"], checks["findings"], checks["code"]) == (
        "same", "same", "different")


def test_a_refresh_that_fails_puts_an_old_case_back_as_it_was_stored(client, tmp_path,
                                                                     monkeypatch):
    """What is written back must be the record itself, not the record as read, or its
    content digest would no longer be its own."""
    store = CaseStore(tmp_path / "case.duckdb")
    before = store.get("old-absent", as_stored=True)
    address = before["address"]
    with duckdb.connect(str(tmp_path / "case.duckdb")) as con:
        con.execute("DELETE FROM cases WHERE id <> 'old-absent'")
    monkeypatch.setattr(main, "make_fetcher",
                        lambda: demo_fetcher(tmp_path / "empty.duckdb", offline=True))
    r = client.post("/api/cases", params={"refresh": "true"}, json={"address": address})
    assert (r.json()["id"], r.json()["status"]) == ("old-absent", "queued")
    after = store.get("old-absent", as_stored=True)
    assert after["status"] == "done" and "Refresh failed" in after["error"]
    assert set(after) == set(before) and "threats" not in after
    assert client.post("/api/cases/old-absent/verify").json()["matches"] is True


def test_a_change_of_status_keeps_the_record_as_it_was_stored(client, tmp_path):
    store = CaseStore(tmp_path / "case.duckdb")
    store.set_status("old-absent", "failed", error="stopped")
    assert "threats" not in store.get("old-absent", as_stored=True)
    assert store.get("old-absent")["threats"] == []


def test_a_record_that_cannot_be_read_is_listed_as_unreadable_and_the_rest_are_listed(
        client, tmp_path):
    put_raw(tmp_path, "c-not-json", "{not json", 1)
    put_raw(tmp_path, "c-no-graph", json.dumps({"id": "c-no-graph", "status": "done"}), 2)
    put_raw(tmp_path, "c-not-a-case", json.dumps(["a", "list"]), 3)
    r = client.get("/api/cases")
    assert r.status_code == 200
    items = {c["id"]: c for c in r.json()["items"]}
    assert set(items) == {"tron-coindcx", *OLD, "c-not-json", "c-no-graph", "c-not-a-case"}
    assert r.json()["total"] == 6
    for cid in ("c-not-json", "c-no-graph", "c-not-a-case"):
        bad = items[cid]
        assert (bad["status"], bad["address"], bad["chain"]) == (
            "failed", "TBrokenRecordAddress", "tron")
        assert "cannot be read" in bad["error"] and cid in bad["error"]
        assert bad["outcome"] is None and bad["risk_score"] is None
    assert items["tron-coindcx"]["status"] == "done"


def test_a_record_that_cannot_be_read_opens_as_a_failed_case_that_says_so(client, tmp_path):
    put_raw(tmp_path, "c-not-json", "{not json")
    r = client.get("/api/cases/c-not-json")
    assert r.status_code == 200
    case = S.CaseDetail.model_validate(r.json())
    assert case.status == "failed" and "cannot be read" in case.error
    assert client.get("/api/cases/c-not-json/pdf").status_code == 409
    assert client.get("/api/cases/c-not-json/receipt").status_code == 409
    assert client.get("/api/dashboard").status_code == 200


def test_a_stored_case_that_no_longer_fits_the_contract_is_listed_as_unreadable(
        client, tmp_path):
    """Readable JSON with every part present, but a value the contract does not allow."""
    case = CaseStore(tmp_path / "case.duckdb").get("tron-coindcx")
    put_raw(tmp_path, "c-odd", json.dumps({**case, "id": "c-odd", "confidence": 7}))
    r = client.get("/api/cases")
    assert r.status_code == 200
    odd = next(c for c in r.json()["items"] if c["id"] == "c-odd")
    assert odd["status"] == "failed" and "cannot be read" in odd["error"]
    assert len(r.json()["items"]) == 4


# ------------------------------------------------------------------ the store itself
def test_the_store_fills_the_newer_fields_on_every_read(client, tmp_path):
    store = CaseStore(tmp_path / "case.duckdb")
    for cid in OLD:
        for case in (store.get(cid), store.get_many([cid])[cid]):
            assert set(ADDED_SINCE) <= set(case)
            assert (case["threats"], case["crossings"], case["chains"]) == ([], [], ["tron"])
    assert all(c["threats"] == [] for c in store.list() if c["id"] in OLD)
    found = store.find("tron", store.get("old-null")["address"])
    assert set(ADDED_SINCE) <= set(found)


def test_the_store_can_give_a_record_exactly_as_it_was_stored(client, tmp_path):
    store = CaseStore(tmp_path / "case.duckdb")
    assert "threats" not in store.get("old-absent", as_stored=True)
    assert store.get("old-null", as_stored=True)["threats"] is None
    assert store.get("nope", as_stored=True) is None


def test_a_current_case_is_read_back_unchanged(client, tmp_path):
    store = CaseStore(tmp_path / "case.duckdb")
    assert store.get("tron-coindcx") == store.get("tron-coindcx", as_stored=True)
