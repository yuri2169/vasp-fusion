"""The API contract: every mock validates against its model, every route answers
with its declared model, and the boundary refuses what it should."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vaspfusion.api import main
from vaspfusion.labels.load import build_labels

FIX = Path(__file__).parent.parent / "fixtures" / "labels"
MOCK_FILES = sorted(p for p in main.MOCKS.rglob("*.json"))


@pytest.fixture(scope="module")
def label_db(tmp_path_factory):
    db = tmp_path_factory.mktemp("api") / "labels.duckdb"
    build_labels(db, FIX / "wa", FIX / "dune.csv")
    return db


@pytest.fixture
def client(label_db, monkeypatch):
    monkeypatch.setattr(main, "LABEL_DB", label_db)
    return TestClient(main.app)


def _rel(p: Path) -> str:
    return p.relative_to(main.MOCKS).with_suffix("").as_posix()


def test_there_are_mocks_for_every_endpoint_family():
    rels = {_rel(p) for p in MOCK_FILES}
    for needed in ("cases", "desk", "dashboard", "model", "labels/search"):
        assert needed in rels
    for prefix in ("cases/", "wallets/", "vasps/", "requests/"):
        assert any(r.startswith(prefix) for r in rels), prefix


@pytest.mark.parametrize("path", MOCK_FILES, ids=_rel)
def test_every_mock_is_marked_demo_and_validates(path):
    data = json.loads(path.read_text())
    assert data.get("_demo") is True
    main.mock_model_for(_rel(path)).model_validate(main.load_mock(_rel(path)))


def test_demo_cases_cover_all_three_outcomes(client):
    items = client.get("/api/cases").json()["items"]
    assert {c["outcome"] for c in items} == {"ATTRIBUTED", "INSUFFICIENT_EVIDENCE",
                                             "SANCTIONED_OR_MIXER_REACHED"}
    for c in items:
        detail = client.get(f"/api/cases/{c['id']}")
        assert detail.status_code == 200 and detail.headers["x-data-source"] == "mock"


def test_abstaining_case_explains_itself(client):
    items = client.get("/api/cases", params={"outcome": "INSUFFICIENT_EVIDENCE"}).json()
    case = client.get(f"/api/cases/{items['items'][0]['id']}").json()
    assert case["abstain_reason"] and case["what_would_change"]
    assert case["top_vasp"] is None


def test_candidates_keep_proximity_and_confidence_apart(client):
    items = client.get("/api/cases", params={"outcome": "ATTRIBUTED"}).json()["items"]
    case = client.get(f"/api/cases/{items[0]['id']}").json()
    ranks = [c["proximity_rank"] for c in case["candidates"]]
    assert ranks == sorted(ranks) and ranks[0] == 1
    assert all("confidence" in c for c in case["candidates"])


@pytest.mark.parametrize("url", ["/api/health", "/api/desk", "/api/dashboard", "/api/model",
                                 "/api/labels/search?q=coindcx"])
def test_get_routes_answer(client, url):
    assert client.get(url).status_code == 200


def test_label_search_is_live_on_the_label_db(client):
    r = client.get("/api/labels/search", params={"q": "coindcx"})
    assert r.headers["x-data-source"] == "live"
    assert r.json()["total"] == 3
    r = client.get("/api/labels/search", params={"category": "swap_service"})
    assert [i["entity"] for i in r.json()["items"]] == ["ChangeNOW"]


def test_wallet_page_reads_live_labels_for_any_address(client):
    r = client.get("/api/wallets/tron/TAa8e7U7seCy7NcZ52xYVQXXybFfwvsUxz")
    assert r.status_code == 200
    assert r.json()["labels"][0]["entity"] == "Bitget"


def test_every_mocked_vasp_request_and_wallet_answers(client):
    for p in MOCK_FILES:
        rel = _rel(p)
        if rel.split("/")[0] in ("vasps", "requests", "wallets") and "/" in rel:
            assert client.get(f"/api/{rel}").status_code == 200, rel


def test_dashboard_label_coverage_is_live(client):
    cov = client.get("/api/dashboard").json()["label_coverage"]
    assert cov["total"] == 15


def test_posting_a_demo_address_returns_its_case(client):
    demo = client.get("/api/cases").json()["items"][0]
    r = client.post("/api/cases", json={"address": demo["address"]})
    assert r.status_code == 202 and r.json()["id"] == demo["id"]


def test_posting_a_new_address_queues_it_with_the_guessed_chain(client):
    r = client.post("/api/cases", json={"address": "0x975d9bd9928f398c7e01f6ba236816fa558cd94b"})
    assert r.status_code == 202
    assert (r.json()["chain"], r.json()["status"]) == ("ethereum", "queued")


def test_unrecognisable_address_is_a_readable_422(client):
    r = client.post("/api/cases", json={"address": "not-a-wallet"})
    assert r.status_code == 422 and "chain" in r.json()["detail"]


@pytest.mark.parametrize("case_id", ["nope", "..", "..%2F..%2Fpyproject"])
def test_unknown_or_hostile_case_ids_are_404(client, case_id):
    assert client.get(f"/api/cases/{case_id}").status_code == 404


def test_patching_a_request_appends_to_its_history(client):
    rid = _rel(next(p for p in MOCK_FILES if _rel(p).startswith("requests/"))).split("/")[1]
    before = client.get(f"/api/requests/{rid}").json()
    r = client.patch(f"/api/requests/{rid}", json={"status": "sent", "note": "via SAHYOG"})
    assert r.status_code == 200
    assert r.json()["status"] == "sent"
    assert len(r.json()["status_history"]) == len(before["status_history"]) + 1
    assert r.json()["letter"]["watermark"] is None


def test_cross_origin_writes_are_refused(client):
    r = client.post("/api/cases", json={"address": "x"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_committed_openapi_matches_the_schemas():
    """docs/openapi.json feeds ui/src/api/types.ts; if this fails, run `make types`."""
    committed = json.loads((main.ROOT / "docs" / "openapi.json").read_text())
    assert committed == json.loads(json.dumps(main.app.openapi()))
