"""The timeline, the write order, the letter-of-request draft and the reply day through
the routes, on the recorded demo wallets. No network."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demokit import SPECS, demo_fetcher, demo_label_db  # noqa: E402
from vaspfusion.api import main  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402

OFFICER = "Insp. A. Rao, Cyber PS"
TWO = "tron-htx-coindcx"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "LABEL_DB", demo_label_db(tmp_path / "labels.duckdb"))
    monkeypatch.setattr(main, "CASE_DB", tmp_path / "case.duckdb")
    monkeypatch.setattr(main, "make_fetcher",
                        lambda: demo_fetcher(tmp_path / "cache.duckdb"))
    monkeypatch.setattr(main, "make_verify_fetcher",
                        lambda: demo_fetcher(tmp_path / "cache.duckdb", offline=True))
    monkeypatch.setenv("ETHERSCAN_API_KEY", "test-key")
    monkeypatch.setenv("TRONGRID_API_KEY", "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")
    monkeypatch.delenv("OFFLINE", raising=False)
    return TestClient(main.app)


def _trace(client, cid) -> str:
    r = client.post("/api/cases", json={"address": SPECS[cid]["address"],
                                        "chain": SPECS[cid]["chain"],
                                        "case_ref": SPECS[cid]["case_ref"]})
    assert r.status_code == 202
    return r.json()["id"]


def _steps(case, state=None):
    return [s for s in case["timeline"]["steps"] if state is None or s["state"] == state]


def test_a_traced_case_has_a_timeline_of_what_was_recorded(client):
    cid = _trace(client, TWO)
    case = client.get(f"/api/cases/{cid}").json()
    S.CaseDetail.model_validate(case)
    done = {s["key"]: s for s in _steps(case, "done")}
    assert done["case_opened"]["source"] == "audit log"
    assert done["trace_started"]["source"] == "trace queue"
    # the result is stored a moment before the queue row closes; whichever second is
    # earlier is the one shown
    assert done["trace_finished"]["source"] in ("trace queue", "case store")
    assert done["exchange_named"]["label"] == "Exchange named: CoinDCX, HTX"
    assert done["exchange_named"]["at"] == done["trace_finished"]["at"]
    assert done["case_opened"]["at"] <= done["trace_started"]["at"] <= done["trace_finished"]["at"]
    assert sorted(s["label"] for s in _steps(case, "pending")) == [
        "Request to CoinDCX: not drafted", "Request to HTX: not drafted"]
    assert not _steps(case, "not_recorded")
    # the views are not part of what the case's digests cover
    assert client.post(f"/api/cases/{cid}/verify").json()["matches"] is True


def test_the_two_exchange_case_says_who_to_write_to_first(client):
    cid = _trace(client, TWO)
    order = client.get(f"/api/cases/{cid}").json()["write_order"]
    assert [(x["rank"], x["vasp"]) for x in order["exchanges"]] == [(1, "CoinDCX"), (2, "HTX")]
    desk = client.get("/api/desk").json()
    assert [w["case_id"] for w in desk["write_first"]] == [cid]


def test_a_request_and_its_reply_day_show_on_the_timeline(client):
    cid = _trace(client, TWO)
    made = client.post("/api/requests", json={"vasp": "CoinDCX", "case_ids": [cid],
                                              "asks": ["kyc"], "officer": OFFICER}).json()
    rid = made["id"]
    assert client.patch(f"/api/requests/{rid}", json={"status": "approved"}).status_code == 200
    due = (datetime.now(timezone.utc).date() + timedelta(days=10)).isoformat()
    r = client.patch(f"/api/requests/{rid}", json={"status": "sent", "due": due})
    assert r.status_code == 200 and (r.json()["due"], r.json()["due_basis"]) == (due, "officer")
    case = client.get(f"/api/cases/{cid}").json()
    keys = [(s["key"], s["state"]) for s in case["timeline"]["steps"]
            if s["request_id"] == rid]
    assert keys == [("request_drafted", "done"), ("request_approved", "done"),
                    ("request_sent", "done"), ("request_acknowledged", "pending"),
                    ("request_replied", "pending")]
    assert case["write_order"]["exchanges"][0]["request_status"] == "sent"
    up = client.get("/api/desk").json()["follow_ups"]
    assert [(f["kind"], f["days_left"]) for f in up] == [("reply_due", 10)]
    r = client.patch(f"/api/requests/{rid}", json={"status": "acknowledged", "due": due})
    assert r.status_code == 422


def test_a_past_reply_day_is_refused(client):
    cid = _trace(client, TWO)
    rid = client.post("/api/requests", json={"vasp": "CoinDCX", "case_ids": [cid],
                                             "asks": ["kyc"], "officer": OFFICER}).json()["id"]
    client.patch(f"/api/requests/{rid}", json={"status": "approved"})
    r = client.patch(f"/api/requests/{rid}", json={"status": "sent", "due": "2020-01-01"})
    assert r.status_code == 422 and "in the past" in r.json()["detail"]


def test_the_letter_of_request_draft_and_its_step(client):
    cid = _trace(client, TWO)
    r = client.get("/api/vasps/HTX/letter-of-request", params={"officer": OFFICER, "cases": cid})
    assert r.status_code == 200
    made = S.LetterOfRequest.model_validate(r.json())
    assert made.letter.kind == "letter_of_request" and made.case_ids == [cid]
    assert made.letter.watermark == "Draft: officer and competent authority review required"
    pdf = client.get(made.pdf_url)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    assert b"NOT SENT" in pdf.content and b"Section 112" in pdf.content
    client.get("/api/vasps/HTX/letter-of-request", params={"officer": OFFICER})    # opened again
    case = client.get(f"/api/cases/{cid}").json()
    drafts = [s for s in case["timeline"]["steps"] if s["key"] == "letter_of_request_drafted"]
    assert len(drafts) == 1 and drafts[0]["source"] == "audit log"
    assert drafts[0]["label"] == "Letter-of-request draft for HTX made"
    assert client.get("/api/requests").json()["items"] == []        # nothing was stored
    assert client.get("/api/desk").json()["rows"][0]["status"] == "not_requested"


def test_the_draft_is_refused_where_the_domestic_notice_applies(client):
    cid = _trace(client, TWO)
    r = client.get("/api/vasps/CoinDCX/letter-of-request", params={"officer": OFFICER})
    assert r.status_code == 422 and "domestic notice applies" in r.json()["detail"]
    r = client.get("/api/vasps/Kraken/letter-of-request", params={"officer": OFFICER})
    assert r.status_code == 404
    assert client.get("/api/vasps/HTX/letter-of-request").status_code == 422   # no officer
    assert cid


def test_the_case_file_carries_the_timeline_and_the_order(client):
    cid = _trace(client, TWO)
    pdf = client.get(f"/api/cases/{cid}/pdf").content
    assert b"CASE TIMELINE" in pdf.upper() and b"WHO TO WRITE TO FIRST" in pdf.upper()
    assert b"from the trace queue" in pdf
