"""The desk routes on the real pipeline: demo cases -> desk -> request -> letter PDF.
Replays the recorded demo wallets; no network."""
import hashlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demokit import SPECS, demo_fetcher, demo_label_db  # noqa: E402
from vaspfusion.api import main  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402

BODY = {"vasp": "CoinDCX", "asks": ["kyc", "transactions", "freeze", "preservation"],
        "officer": "Insp. A. Rao, Cyber PS"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "LABEL_DB", demo_label_db(tmp_path / "labels.duckdb"))
    monkeypatch.setattr(main, "CASE_DB", tmp_path / "case.duckdb")
    monkeypatch.setattr(main, "DESK_DB", tmp_path / "desk.duckdb")
    monkeypatch.setattr(main, "OUTBOX", tmp_path / "outbox")
    monkeypatch.setattr(main, "make_fetcher",
                        lambda: demo_fetcher(tmp_path / "cache.duckdb"))
    monkeypatch.setenv("ETHERSCAN_API_KEY", "test-key")
    monkeypatch.setenv("TRONGRID_API_KEY", "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")
    monkeypatch.delenv("OFFLINE", raising=False)
    c = TestClient(main.app)
    c.outbox = tmp_path / "outbox"
    return c


def _trace(client, *case_ids) -> list[str]:
    ids = []
    for cid in case_ids:
        r = client.post("/api/cases", json={"address": SPECS[cid]["address"],
                                            "chain": SPECS[cid]["chain"],
                                            "case_ref": SPECS[cid]["case_ref"]})
        assert r.status_code == 202
        ids.append(r.json()["id"])
    return ids


def test_with_no_live_case_the_desk_is_the_mock(client):
    r = client.get("/api/desk")
    assert r.status_code == 200 and r.headers["x-data-source"] == "mock"
    assert client.get("/api/vasps/OKX").headers["x-data-source"] == "mock"
    assert client.get("/api/requests/demo-req-okx-001").headers["x-data-source"] == "mock"


def test_from_demo_cases_to_the_desk_to_a_sent_letter(client):
    a, b = _trace(client, "tron-coindcx", "tron-htx-coindcx")
    desk = client.get("/api/desk")
    assert desk.headers["x-data-source"] == "live"
    S.Desk.model_validate(desk.json())
    rows = {r["vasp"]: r for r in desk.json()["rows"]}
    assert set(rows) == {"CoinDCX", "HTX"}
    assert sorted(rows["CoinDCX"]["case_ids"]) == sorted([a, b])
    assert (rows["CoinDCX"]["wallet_count"], rows["CoinDCX"]["total_usd"]) == (2, 7530.0)

    r = client.post("/api/requests", json={**BODY, "case_ids": [a, b]})
    assert r.status_code == 201 and r.headers["x-data-source"] == "live"
    req = r.json()
    S.RequestDetail.model_validate(req)
    rid = req["id"]
    assert req["status"] == "drafted" and req["pdf_url"] == f"/api/requests/{rid}/pdf"
    assert [w["case_ref"] for w in req["letter"]["wallets"]] == ["DEMO/2026/101", "DEMO/2026/104"]
    assert client.get(f"/api/requests/{rid}").json() == req

    draft = client.get(req["pdf_url"])
    assert draft.status_code == 200 and draft.headers["content-type"] == "application/pdf"
    assert draft.headers["x-data-source"] == "live"
    assert draft.headers["content-disposition"] == f'inline; filename="{rid}-draft.pdf"'
    assert draft.content[:5] == b"%PDF-" and b"DRAFT - OFFICER REVIEW REQUIRED" in draft.content
    assert client.get(f"/api/requests/{rid}.pdf").content == draft.content

    assert client.patch(f"/api/requests/{rid}", json={"status": "sent"}).status_code == 409
    r = client.patch(f"/api/requests/{rid}", json={"status": "approved", "note": "SHO"})
    assert r.status_code == 200 and r.json()["letter"]["watermark"] is None
    sent = client.patch(f"/api/requests/{rid}", json={"status": "sent"}).json()
    assert sent["status"] == "sent" and sent["due"] and sent["receipt"]["gateway"] == "mock-outbox"
    final = client.get(f"/api/requests/{rid}/pdf")
    assert b"DRAFT" not in final.content
    assert final.headers["content-disposition"] == f'inline; filename="{rid}.pdf"'
    assert sent["payload"]["documents"][0]["sha256"] == hashlib.sha256(final.content).hexdigest()
    assert json.loads((client.outbox / f"{rid}.json").read_text()) == sent["payload"]

    row = next(r for r in client.get("/api/desk").json()["rows"] if r["vasp"] == "CoinDCX")
    assert (row["status"], row["last_request_id"], row["unrequested_wallets"]) == ("sent", rid, 0)
    page = client.get("/api/vasps/CoinDCX")
    assert page.headers["x-data-source"] == "live"
    S.VaspDetail.model_validate(page.json())
    assert page.json()["directory"]["legal_name"] == "Neblio Technologies Private Limited"
    assert [q["id"] for q in page.json()["requests"]] == [rid]
    assert page.json()["label_counts"]["tron"] >= 1


def test_what_the_evidence_does_not_support_is_refused_in_words(client):
    (abstain,) = _trace(client, "tron-abstain")
    r = client.post("/api/requests", json={**BODY, "case_ids": [abstain]})
    assert r.status_code == 422 and "under the 0.60 needed" in r.json()["detail"]
    r = client.post("/api/requests", json={**BODY, "case_ids": ["no-such-case"]})
    assert r.status_code == 404
    assert client.patch("/api/requests/req-2026-0404", json={"status": "sent"}).status_code == 404
    assert client.get("/api/requests/req-2026-0404/pdf").status_code == 404
    assert client.get("/api/requests/req-2026-0404.pdf").status_code == 404
    assert client.get("/api/vasps/No%20Such%20Exchange").status_code == 404


def test_a_directory_exchange_with_no_case_still_has_its_page(client):
    r = client.get("/api/vasps/Bitrue")
    assert r.status_code == 200 and r.headers["x-data-source"] == "live"
    d = r.json()["directory"]
    assert (d["fiu_ind_registered"], d["fiu_ind_as_of"]) == (False, "2025-10-01")
    assert r.json()["wallets"] == [] and r.json()["requests"] == []


def test_the_mock_request_still_answers_and_its_pdf_is_marked_demo(client):
    r = client.post("/api/requests", json={**BODY, "vasp": "OKX", "case_ids": ["demo-tron-okx"]})
    assert r.status_code == 201 and r.headers["x-data-source"] == "mock"
    pdf = client.get("/api/requests/demo-req-okx-001/pdf")
    assert pdf.status_code == 200 and b"DEMO FIXTURE - NOT EVIDENCE" in pdf.content
    assert pdf.headers["x-data-source"] == "mock"
    # a demo case that does not name the exchange gets no request, mock or not
    for cid in ("demo-eth-abstain", "demo-tron-sanctioned"):
        r = client.post("/api/requests", json={**BODY, "vasp": "OKX", "case_ids": [cid]})
        assert r.status_code == 422 and "does not name that exchange" in r.json()["detail"]
    (live,) = _trace(client, "tron-coindcx")
    r = client.post("/api/requests", json={**BODY, "case_ids": ["demo-tron-okx", live]})
    assert r.status_code == 404                     # a demo id is not a traced case


def test_asking_twice_is_a_409_and_a_withdrawn_draft_can_be_redone(client):
    (cid,) = _trace(client, "tron-coindcx")
    rid = client.post("/api/requests", json={**BODY, "case_ids": [cid]}).json()["id"]
    again = client.post("/api/requests", json={**BODY, "case_ids": [cid]})
    assert again.status_code == 409 and rid in again.json()["detail"]
    gone = client.patch(f"/api/requests/{rid}", json={"status": "withdrawn"})
    assert gone.status_code == 200 and gone.json()["allowed_next"] == []
    assert client.post("/api/requests", json={**BODY, "case_ids": [cid]}).status_code == 201
    assert client.get("/api/vasps/coindcx").json()["directory"]["name"] == "CoinDCX"


def test_the_register_lists_every_request_newest_first(client):
    mock = client.get("/api/requests")            # no live case yet: the demo request
    assert mock.status_code == 200 and mock.headers["x-data-source"] == "mock"
    S.RequestList.model_validate(mock.json())
    assert [q["id"] for q in mock.json()["items"]] == ["demo-req-okx-001"]

    a, b = _trace(client, "tron-coindcx", "tron-htx-coindcx")
    empty = client.get("/api/requests")           # live cases, nothing drafted: no demo row
    assert empty.headers["x-data-source"] == "live" and empty.json() == {"items": []}

    first = client.post("/api/requests", json={**BODY, "case_ids": [a, b]}).json()
    client.patch(f"/api/requests/{first['id']}", json={"status": "withdrawn"})
    second = client.post("/api/requests", json={**BODY, "vasp": "HTX", "case_ids": [b]}).json()
    listed = client.get("/api/requests")
    S.RequestList.model_validate(listed.json())
    items = listed.json()["items"]
    assert [q["id"] for q in items] == [second["id"], first["id"]]
    assert items[1]["status"] == "withdrawn" and items[1]["allowed_next"] == []
    assert items[0] == client.get(f"/api/requests/{second['id']}").json()
    assert [q["id"] for q in client.get("/api/requests?vasp=htx").json()["items"]] == [second["id"]]
    assert [q["id"] for q in client.get("/api/requests?status=withdrawn").json()["items"]] == [first["id"]]
