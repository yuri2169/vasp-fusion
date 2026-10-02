"""The case file, the receipt and verify over the API, on the real pipeline replaying
the recorded demo wallets. No network."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demokit import SPECS, demo_fetcher, demo_label_db  # noqa: E402
from vaspfusion import provenance as P  # noqa: E402
from vaspfusion.api import main  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402
from vaspfusion.chains.cache import ChainCache, Fetcher  # noqa: E402

COINDCX = SPECS["tron-coindcx"]["address"]
BITGET = SPECS["eth-bitget"]["address"]


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
    return TestClient(main.app)


def open_case(client, address=COINDCX, **body) -> str:
    return client.post("/api/cases", json={"address": address, **body}).json()["id"]


# ------------------------------------------------------------------ the PDF
def test_the_case_file_is_served_as_a_pdf(client):
    cid = open_case(client, case_ref="FIR 12/2026")
    r = client.get(f"/api/cases/{cid}/pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["x-data-source"] == "live"
    assert r.headers["content-disposition"] == f'inline; filename="case-{cid}.pdf"'
    assert r.content.startswith(b"%PDF-") and COINDCX.encode() in r.content
    assert b"FIR 12/2026" in r.content and b"Demonstration case" not in r.content
    again = client.get(f"/api/cases/{cid}.pdf")
    assert again.status_code == 200 and again.content == r.content     # same case, same bytes


def test_a_mock_fixture_case_is_watermarked(client):
    r = client.get("/api/cases/demo-tron-okx/pdf")
    assert r.status_code == 200 and r.headers["x-data-source"] == "mock"
    assert b"DEMO FIXTURE - NOT EVIDENCE" in r.content
    assert 'filename="case-demo-tron-okx-demo.pdf"' in r.headers["content-disposition"]


def test_a_case_without_a_result_has_no_file(client, monkeypatch):
    monkeypatch.setattr(main, "_run_case", lambda *a, **k: None)      # the trace never runs
    cid = open_case(client)
    r = client.get(f"/api/cases/{cid}/pdf")
    assert r.status_code == 409 and "no result yet" in r.json()["detail"]
    assert client.get(f"/api/cases/{cid}/receipt").status_code == 409


def test_an_unknown_case_is_404_on_every_export(client):
    assert client.get("/api/cases/nope/pdf").status_code == 404
    assert client.get("/api/cases/nope.pdf").status_code == 404
    assert client.get("/api/cases/nope/receipt").status_code == 404
    assert client.post("/api/cases/nope/verify").status_code == 404


def test_the_case_route_still_answers_json(client):
    cid = open_case(client)
    r = client.get(f"/api/cases/{cid}")
    assert r.headers["content-type"].startswith("application/json")
    S.CaseDetail.model_validate(r.json())


# ------------------------------------------------------------------ the receipt
def test_the_receipt_is_the_case_as_digests(client):
    cid = open_case(client, max_hops=3)
    case = client.get(f"/api/cases/{cid}").json()
    r = client.get(f"/api/cases/{cid}/receipt")
    assert r.status_code == 200 and r.headers["x-data-source"] == "live"
    doc = r.json()
    S.Receipt.model_validate(doc)
    assert doc["schema"] == "vaspfusion-receipt/1" and doc["case_id"] == cid
    assert doc["input"] == {"address": COINDCX, "chain": "tron", "max_hops": 3, "since": None}
    assert doc["findings_sha256"] == P.findings_sha256(case)
    assert doc["label_db_sha256"] == P.file_sha256(main.LABEL_DB)
    assert doc["pages"] == len(doc["responses"]) > 0


# ------------------------------------------------------------------ verify
def test_verify_traces_again_from_the_cache_and_matches(client):
    cid = open_case(client)
    r = client.post(f"/api/cases/{cid}/verify")
    assert r.status_code == 200
    result = r.json()
    S.VerifyResult.model_validate(result)
    assert result["matches"] is True and result["summary"].startswith("Verified")
    checks = {c["name"]: c["result"] for c in result["checks"]}
    assert checks["labels"] == "same" and checks["findings"] == "same"


def test_verify_an_ethereum_case(client):
    cid = open_case(client, BITGET)
    assert client.post(f"/api/cases/{cid}/verify").json()["matches"] is True


def test_verify_catches_a_case_edited_in_the_store(client):
    cid = open_case(client)
    store = main._cases()
    case = store.get(cid)
    case["top_vasp"] = "Binance"
    store.save(case)
    result = client.post(f"/api/cases/{cid}/verify").json()
    assert result["matches"] is False
    assert "changed after it was computed" in result["summary"]


def test_verify_never_fetches(client, monkeypatch, tmp_path):
    cid = open_case(client)
    monkeypatch.setattr(main, "make_verify_fetcher",
                        lambda: Fetcher(ChainCache(tmp_path / "empty.duckdb"), None, offline=True))
    result = client.post(f"/api/cases/{cid}/verify").json()
    assert result["matches"] is False and "could not be traced again" in result["summary"]


def test_a_mock_fixture_cannot_be_verified(client):
    r = client.post("/api/cases/demo-tron-okx/verify")
    assert r.status_code == 422 and "no trace to verify" in r.json()["detail"]
