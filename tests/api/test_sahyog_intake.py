"""SAHYOG, both directions, on the real pipeline: a complaint comes in, its wallets are
traced with nobody touching the tool, the result goes back through the gateway, a
request goes out and the exchange's reply comes in. Replays the recorded demo wallets;
no network. SAHYOG's own interface is not public: this is our side of the contract."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demokit import SPECS, demo_fetcher, demo_label_db  # noqa: E402
from vaspfusion.api import main  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402
from vaspfusion.desk import intake  # noqa: E402

COINDCX = SPECS["tron-coindcx"]["address"]
OFAC = SPECS["tron-ofac"]["address"]
BITGET = SPECS["eth-bitget"]["address"]
KEY = {"X-SAHYOG-Key": "a-key-for-this-test-only"}


def body(ref="NCRP-2026-0001", wallets=(COINDCX,), **over) -> dict:
    return {"complaint_ref": ref, "agency": "Cyber PS, Test District",
            "officer": "SI R. Example", "category": "investment_fraud",
            "amount_lost_inr": 250000, "note": "reported by the complainant",
            "wallets": [{"address": a} for a in wallets], **over}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "LABEL_DB", demo_label_db(tmp_path / "labels.duckdb"))
    monkeypatch.setattr(main, "CASE_DB", tmp_path / "case.duckdb")
    monkeypatch.setattr(main, "make_fetcher",
                        lambda: demo_fetcher(tmp_path / "cache.duckdb"))
    monkeypatch.setenv("ETHERSCAN_API_KEY", "test-key")
    monkeypatch.setenv("TRONGRID_API_KEY", "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")
    monkeypatch.delenv("OFFLINE", raising=False)
    monkeypatch.setenv("SAHYOG_API_KEY", KEY["X-SAHYOG-Key"])
    c = TestClient(main.app)
    c.outbox = tmp_path / "outbox"
    return c


# ------------------------------------------------------------------ the key
def test_without_a_configured_key_the_intake_is_closed(client, monkeypatch):
    monkeypatch.delenv("SAHYOG_API_KEY")
    r = client.post("/api/sahyog/complaints", json=body(), headers=KEY)
    assert r.status_code == 503 and "not configured" in r.json()["detail"]
    assert client.get("/api/sahyog-sim").json()["enabled"] is False
    assert client.post("/api/sahyog-sim/complaints", json=body()).status_code == 503


@pytest.mark.parametrize("headers", [{}, {"X-SAHYOG-Key": "wrong"}])
def test_a_missing_or_wrong_key_is_refused_on_every_route(client, headers):
    for call in (lambda: client.post("/api/sahyog/complaints", json=body(), headers=headers),
                 lambda: client.get("/api/sahyog/complaints/NCRP-2026-0001", headers=headers),
                 lambda: client.post("/api/sahyog/requests/req-2026-0001/replies",
                                     json={"status": "acknowledged"}, headers=headers)):
        r = call()
        assert r.status_code == 401 and "X-SAHYOG-Key" in r.json()["detail"]
    assert client.get("/api/cases").json()["total"] == len(main._demo_cases())


def test_the_key_stands_in_for_an_officers_login_on_the_intake_only(client, monkeypatch):
    monkeypatch.setattr(main, "AUTH", "required")
    assert client.get("/api/cases").status_code == 401
    assert client.get("/api/sahyog-sim").status_code == 401         # the simulator is the officer's
    r = client.post("/api/sahyog/complaints", json=body(), headers=KEY)
    assert r.status_code == 202
    assert client.post("/api/sahyog/complaints", json=body()).status_code == 401


def test_the_demo_key_is_random_and_written_once(tmp_path):
    file, made = intake.ensure_demo_key(tmp_path / "k")
    again, made_again = intake.ensure_demo_key(tmp_path / "k")
    assert made and not made_again and file == again
    assert len(file.read_text().strip()) >= 40
    assert intake.configured_key(tmp_path / "k") == file.read_text().strip()


# ------------------------------------------------------------------ complaint in
def test_a_complaint_is_traced_without_anyone_touching_the_tool(client):
    r = client.post("/api/sahyog/complaints", json=body(wallets=(COINDCX, OFAC)), headers=KEY)
    assert r.status_code == 202
    S.ComplaintStatus.model_validate(r.json())
    ids = [w["case_id"] for w in r.json()["wallets"]]
    assert len(set(ids)) == 2 and all(r.json()["wallets"][i]["accepted"] for i in (0, 1))

    # nothing else is called: the status route alone shows the finished result
    status = client.get("/api/sahyog/complaints/NCRP-2026-0001", headers=KEY).json()
    S.ComplaintStatus.model_validate(status)
    assert status["status"] == "result"
    one, two = status["wallets"]
    assert (one["status"], one["outcome"], one["top_vasp"]) == ("result", "ATTRIBUTED", "CoinDCX")
    assert one["exchanges"][0]["vasp"] == "CoinDCX"
    assert one["exchanges"][0]["hops"] == 1 and 0.6 <= one["exchanges"][0]["confidence"] <= 1
    assert one["risk_class"] == "low" and one["report_pdf"] == f"/api/cases/{ids[0]}/pdf"
    assert (two["outcome"], two["top_vasp"], two["risk_class"]) == \
        ("SANCTIONED_OR_MIXER_REACHED", None, "severe")
    assert client.get(one["report_pdf"]).content.startswith(b"%PDF")

    # the case is an ordinary case, and says where it came from
    case = client.get(f"/api/cases/{ids[0]}").json()
    S.CaseDetail.model_validate(case)
    assert case["sahyog_complaint_ref"] == "NCRP-2026-0001"
    assert case["complaint_no"] == "NCRP-2026-0001" and case["amount_lost_inr"] == 250000
    listed = {c["id"]: c for c in client.get("/api/cases").json()["items"]}
    assert listed[ids[0]]["sahyog_complaint_ref"] == "NCRP-2026-0001"
    assert listed[ids[1]]["risk_class"] == "severe"


def test_the_result_is_handed_to_the_gateway(client):
    r = client.post("/api/sahyog/complaints", headers=KEY,
                    json=body(callback_url="https://portal.example/cb"))
    cid = r.json()["wallets"][0]["case_id"]
    file = client.outbox / "results" / f"NCRP-2026-0001__{cid}.json"
    payload = json.loads(file.read_text())
    assert payload["schema"] == "vaspfusion-sahyog-result/1"
    assert payload["complaint_ref"] == "NCRP-2026-0001"
    assert payload["callback_url"] == "https://portal.example/cb"     # recorded, never called
    assert (payload["wallet"]["top_vasp"], payload["wallet"]["risk_class"]) == ("CoinDCX", "low")
    assert "Not a probability" in payload["risk_basis"]
    sent = client.get("/api/sahyog/complaints/NCRP-2026-0001", headers=KEY).json()
    assert sent["wallets"][0]["result_sent_at"] is not None


def test_the_same_complaint_again_returns_the_same_cases_and_traces_nothing(client, monkeypatch):
    first = client.post("/api/sahyog/complaints", json=body(), headers=KEY).json()
    runs = []
    monkeypatch.setattr(main, "_run_case", lambda *a, **k: runs.append(a))
    again = client.post("/api/sahyog/complaints", json=body(), headers=KEY)
    assert again.status_code == 202 and runs == []
    assert [w["case_id"] for w in again.json()["wallets"]] == \
        [w["case_id"] for w in first["wallets"]]
    assert len(again.json()["wallets"]) == 1


def test_a_wallet_added_to_a_complaint_is_traced_and_the_first_is_not_traced_again(client):
    client.post("/api/sahyog/complaints", json=body(), headers=KEY)
    r = client.post("/api/sahyog/complaints", json=body(wallets=(COINDCX, BITGET)), headers=KEY)
    assert [w["address"] for w in r.json()["wallets"]] == [COINDCX, BITGET]
    status = client.get("/api/sahyog/complaints/NCRP-2026-0001", headers=KEY).json()
    assert [w["top_vasp"] for w in status["wallets"]] == ["CoinDCX", "Bitget"]


def test_a_bad_address_is_refused_by_name_and_the_good_ones_go_through(client):
    r = client.post("/api/sahyog/complaints", headers=KEY,
                    json=body(wallets=("not-an-address", COINDCX, "T" + "1" * 33)))
    assert r.status_code == 202
    bad, good, bad2 = r.json()["wallets"]
    assert (bad["accepted"], bad["status"], bad["case_id"]) == (False, "refused", None)
    assert bad["error"].startswith("not-an-address: Could not tell which chain")
    assert bad2["accepted"] is False and bad2["address"] in bad2["error"]
    assert good["accepted"] is True and good["case_id"]
    status = client.get("/api/sahyog/complaints/NCRP-2026-0001", headers=KEY).json()
    assert status["status"] == "result" and len(status["wallets"]) == 3


def test_a_complaint_with_no_usable_wallet_is_refused_whole(client):
    r = client.post("/api/sahyog/complaints", json=body(wallets=("nope",)), headers=KEY)
    assert r.status_code == 422 and "No wallet in this complaint" in r.json()["detail"]
    assert client.get("/api/sahyog/complaints/NCRP-2026-0001", headers=KEY).status_code == 404


@pytest.mark.parametrize("change,where", [
    ({"complaint_ref": "has a space"}, "complaint_ref"),
    ({"complaint_ref": "../etc"}, "complaint_ref"),
    ({"wallets": []}, "wallets"),
    ({"agency": ""}, "agency"),
    ({"category": "nonsense"}, "category"),
    ({"amount_lost_inr": -1}, "amount_lost_inr"),
])
def test_a_malformed_complaint_is_a_422_naming_the_field(client, change, where):
    r = client.post("/api/sahyog/complaints", json={**body(), **change}, headers=KEY)
    assert r.status_code == 422 and where in json.dumps(r.json())


def test_an_unknown_complaint_is_a_404(client):
    r = client.get("/api/sahyog/complaints/NCRP-0000", headers=KEY)
    assert r.status_code == 404 and "NCRP-0000" in r.json()["detail"]


def test_a_wallet_that_already_had_a_case_is_linked_and_reported_at_once(client):
    cid = client.post("/api/cases", json={"address": COINDCX}).json()["id"]
    r = client.post("/api/sahyog/complaints", json=body(), headers=KEY).json()
    assert r["wallets"][0]["case_id"] == cid and r["wallets"][0]["status"] == "result"
    assert r["wallets"][0]["result_sent_at"] is not None
    assert (client.outbox / "results" / f"NCRP-2026-0001__{cid}.json").exists()


# ------------------------------------------------------------------ request out, reply in
def _sent_request(client) -> tuple[str, str]:
    cid = client.post("/api/sahyog/complaints", json=body(),
                      headers=KEY).json()["wallets"][0]["case_id"]
    req = client.post("/api/requests", json={
        "vasp": "CoinDCX", "case_ids": [cid], "asks": ["kyc", "freeze"],
        "officer": "Insp. A. Rao, Cyber PS"}).json()
    for status in ("approved", "sent"):
        assert client.patch(f"/api/requests/{req['id']}", json={"status": status}).status_code == 200
    return cid, req["id"]


def test_the_round_trip_ends_with_the_freeze_confirmed_on_the_desk(client):
    cid, rid = _sent_request(client)
    status = client.get("/api/sahyog/complaints/NCRP-2026-0001", headers=KEY).json()
    assert status["wallets"][0]["request_ids"] == [rid]

    r = client.post(f"/api/sahyog/requests/{rid}/replies", headers=KEY,
                    json={"status": "acknowledged", "reply_ref": "CDX-LE-7781"})
    assert r.status_code == 200
    S.ReplyAck.model_validate(r.json())
    assert r.json()["status"] == "acknowledged"
    assert r.json()["location"] == f"outbox/replies/{rid}.acknowledged.json"
    r = client.post(f"/api/sahyog/requests/{rid}/replies", headers=KEY,
                    json={"status": "freeze_confirmed", "note": "Account frozen."})
    assert r.json()["status"] == "freeze_confirmed"

    req = client.get(f"/api/requests/{rid}").json()
    S.RequestDetail.model_validate(req)
    assert req["status"] == "freeze_confirmed" and req["allowed_next"] == []
    last = req["status_history"][-1]
    assert last["via"] == "sahyog" and "Account frozen." in last["note"]
    assert "Reply received through SAHYOG (mock-outbox)" in last["note"]
    assert "CDX-LE-7781" in req["status_history"][-2]["note"]
    row = next(x for x in client.get("/api/desk").json()["rows"] if x["vasp"] == "CoinDCX")
    assert row["status"] == "freeze_confirmed"
    kept = json.loads((client.outbox / "replies" / f"{rid}.freeze_confirmed.json").read_text())
    assert kept["schema"] == "vaspfusion-sahyog-reply/1" and kept["note"] == "Account frozen."


def test_a_reply_that_cannot_follow_is_refused_and_a_repeat_changes_nothing(client):
    _, rid = _sent_request(client)
    url = f"/api/sahyog/requests/{rid}/replies"
    assert client.post(url, json={"status": "refused"}, headers=KEY).status_code == 200
    r = client.post(url, json={"status": "acknowledged"}, headers=KEY)
    assert r.status_code == 409 and "It is closed" in r.json()["detail"]
    before = client.get(f"/api/requests/{rid}").json()["status_history"]
    again = client.post(url, json={"status": "refused"}, headers=KEY)
    assert again.status_code == 200 and again.json()["location"] is None
    assert client.get(f"/api/requests/{rid}").json()["status_history"] == before
    assert client.post(url, json={"status": "sent"}, headers=KEY).status_code == 422
    assert client.post("/api/sahyog/requests/req-2026-9999/replies",
                       json={"status": "acknowledged"}, headers=KEY).status_code == 404


def test_a_request_that_was_never_sent_cannot_be_replied_to(client):
    cid = client.post("/api/sahyog/complaints", json=body(),
                      headers=KEY).json()["wallets"][0]["case_id"]
    rid = client.post("/api/requests", json={
        "vasp": "CoinDCX", "case_ids": [cid], "asks": ["kyc"],
        "officer": "Insp. A. Rao"}).json()["id"]
    r = client.post(f"/api/sahyog/requests/{rid}/replies", json={"status": "acknowledged"},
                    headers=KEY)
    assert r.status_code == 409 and "has not been sent" in r.json()["detail"]


# ------------------------------------------------------------------ the simulator
def test_the_simulator_files_through_the_same_intake_and_plays_the_exchange(client):
    sim = client.get("/api/sahyog-sim").json()
    S.SahyogSim.model_validate(sim)
    assert sim["enabled"] and sim["notice"] == \
        "A simulator for demonstration. Not the SAHYOG portal."
    assert sim["complaints"] == [] and sim["requests"] == []

    r = client.post("/api/sahyog-sim/complaints", json=body(ref="SIM-1"))
    assert r.status_code == 202
    cid = r.json()["wallets"][0]["case_id"]
    # the very complaint the keyed route reads
    assert client.get("/api/sahyog/complaints/SIM-1", headers=KEY).json()["status"] == "result"
    rid = client.post("/api/requests", json={
        "vasp": "CoinDCX", "case_ids": [cid], "asks": ["freeze"],
        "officer": "Insp. A. Rao"}).json()["id"]
    assert client.get("/api/sahyog-sim").json()["requests"] == []     # a draft is not there
    for status in ("approved", "sent"):
        client.patch(f"/api/requests/{rid}", json={"status": status})
    sim = client.get("/api/sahyog-sim").json()
    S.SahyogSim.model_validate(sim)
    assert [c["complaint_ref"] for c in sim["complaints"]] == ["SIM-1"]
    seen = sim["requests"][0]
    assert (seen["id"], seen["vasp"], seen["status"], seen["asks"]) == \
        (rid, "CoinDCX", "sent", ["freeze"])
    assert seen["allowed_replies"] == ["acknowledged", "answered", "freeze_confirmed", "refused"]

    r = client.post(f"/api/sahyog-sim/requests/{rid}/reply", json={"status": "freeze_confirmed"})
    assert r.status_code == 200 and r.json()["status"] == "freeze_confirmed"
    assert client.get("/api/sahyog-sim").json()["requests"][0]["allowed_replies"] == []
    assert client.get(f"/api/requests/{rid}").json()["status"] == "freeze_confirmed"


def test_every_sahyog_call_is_in_the_audit_log(client):
    client.post("/api/sahyog/complaints", json=body(), headers=KEY)
    client.post("/api/sahyog/complaints", json=body(), headers={"X-SAHYOG-Key": "wrong"})
    client.get("/api/sahyog/complaints/NCRP-2026-0001", headers=KEY)
    client.get("/api/sahyog-sim")
    rows = client.get("/api/audit").json()["items"]
    S.AuditPage.model_validate(client.get("/api/audit").json())
    seen = {(r["action"], r["status"], r["target"]) for r in rows}
    assert ("sahyog.complaint", 202, "NCRP-2026-0001") in seen
    assert ("sahyog.complaint", 401, None) in seen
    assert ("sahyog.status", 200, "NCRP-2026-0001") in seen
    assert ("sim.view", 200, None) in seen
