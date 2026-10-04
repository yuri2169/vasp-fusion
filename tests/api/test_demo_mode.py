"""VASPFUSION_DEMO_MODE (U5). Off, which is the default, the API answers from its stores
only: an empty store gives an empty answer or a 404 in a sentence, never a fixture from
mocks/. On, the B1 fixtures stand in as before."""
import pytest
from fastapi.testclient import TestClient

from vaspfusion.api import main

OKX_DEMO_WALLET = "TJmVZbgQGXQHDcQGfhDp1D5Y5vJFvSZc1v"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CASE_DB", tmp_path / "case.duckdb")
    monkeypatch.setattr(main, "LABEL_DB", tmp_path / "no-labels.duckdb")
    monkeypatch.setattr(main, "MODEL_DIR", tmp_path / "no-model")
    monkeypatch.delenv("VASPFUSION_DEMO_MODE", raising=False)
    return TestClient(main.app)


def test_demo_mode_is_off_unless_asked_for(client, monkeypatch):
    assert main.demo_mode() is False
    for on in ("1", "true", "on"):
        monkeypatch.setenv("VASPFUSION_DEMO_MODE", on)
        assert main.demo_mode() is True
    monkeypatch.setenv("VASPFUSION_DEMO_MODE", "0")
    assert main.demo_mode() is False


def test_health_says_which_mode(client, monkeypatch):
    assert client.get("/api/health").json()["data_mode"] == "live"
    monkeypatch.setenv("VASPFUSION_DEMO_MODE", "1")
    assert client.get("/api/health").json()["data_mode"] == "mixed"


def test_no_fixture_case_is_listed_or_served(client):
    r = client.get("/api/cases")
    assert r.json() == {"total": 0, "items": []} and r.headers["x-data-source"] == "live"
    for path in ("/api/cases/demo-tron-okx", "/api/cases/demo-tron-okx/receipt",
                 "/api/cases/demo-tron-okx/pdf"):
        r = client.get(path)
        assert r.status_code == 404, path
        assert "demo-tron-okx" in r.json()["detail"] and "case" in r.json()["detail"].lower()
    assert client.post("/api/cases/demo-tron-okx/verify").status_code == 404


def test_a_fixture_wallet_is_not_answered_from_the_fixture(client):
    address = next(c["address"] for c in main.load_mock("cases")["items"])
    r = client.post("/api/cases", json={"address": address})
    assert r.headers.get("x-data-source") != "mock"
    assert r.status_code != 202 or r.json()["id"] != "demo-tron-okx"


def test_the_desk_and_the_register_are_empty_not_fixtures(client):
    r = client.get("/api/desk")
    assert r.status_code == 200 and r.headers["x-data-source"] == "live"
    assert r.json()["rows"] == []
    r = client.get("/api/requests")
    assert r.json() == {"items": []} and r.headers["x-data-source"] == "live"
    for call in (client.get("/api/requests/req-demo-0001"),
                 client.get("/api/requests/req-demo-0001/pdf"),
                 client.patch("/api/requests/req-demo-0001", json={"status": "approved"})):
        assert call.status_code == 404
        assert "request" in call.json()["detail"].lower()


def test_a_request_for_fixture_cases_goes_to_the_real_desk(client):
    r = client.post("/api/requests", json={"vasp": "OKX", "case_ids": ["demo-tron-okx"],
                                           "asks": ["kyc"], "officer": "Insp. A. Rao"})
    assert r.headers.get("x-data-source") != "mock"
    assert r.status_code in (404, 409, 422)


def test_the_dashboard_counts_nothing(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200 and r.headers["x-data-source"] == "live"
    body = r.json()
    assert body["counts"]["cases_total"] == 0
    assert body["top_vasps"] == [] and body["label_coverage"]["total"] == 0


def test_no_label_database_is_said_in_a_sentence(client):
    for path in ("/api/labels/coverage", "/api/labels/search?q=okx"):
        r = client.get(path)
        assert r.status_code == 503 and "make labels" in r.json()["detail"]


def test_an_unmeasured_model_says_so_and_shows_no_figure(client):
    r = client.get("/api/model")
    assert r.status_code == 200 and r.headers["x-data-source"] == "live"
    body = r.json()
    assert body["status"] == "not_measured"
    assert body["reliability"] == [] and body["feature_importance"] == []
    assert all(v is None for v in body["metrics"].values())


def test_an_exchange_nobody_knows_is_404_not_a_fixture_page(client, monkeypatch):
    r = client.get("/api/vasps/Nonexistent Exchange")
    assert r.status_code == 404 and "Nothing is on file" in r.json()["detail"]


def test_with_demo_mode_on_the_fixtures_stand_in(client, monkeypatch):
    monkeypatch.setenv("VASPFUSION_DEMO_MODE", "1")
    r = client.get("/api/cases")
    assert r.json()["total"] == 3 and r.headers["x-data-source"] == "mock"
    assert client.get("/api/cases/demo-tron-okx").status_code == 200
    assert client.get("/api/desk").headers["x-data-source"] == "mock"
    assert client.get("/api/model").headers["x-data-source"] == "mock"
