"""The case routes on the real pipeline: POST a wallet, the trace runs, GET returns it.
Replays the recorded demo wallets; no network."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demokit import SPECS, demo_fetcher, demo_label_db  # noqa: E402
from vaspfusion.api import main  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402

COINDCX = SPECS["tron-coindcx"]["address"]
BITGET = SPECS["eth-bitget"]["address"]
COINDCX_2 = "TU7BbAsb8t371eMijQeiGXsiLvY1vZbsFs"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "LABEL_DB", demo_label_db(tmp_path / "labels.duckdb"))
    monkeypatch.setattr(main, "CASE_DB", tmp_path / "case.duckdb")
    monkeypatch.setattr(main, "make_fetcher",
                        lambda: demo_fetcher(tmp_path / "cache.duckdb"))
    monkeypatch.setenv("ETHERSCAN_API_KEY", "test-key")   # selects the recorded backend
    monkeypatch.setenv("TRONGRID_API_KEY", "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")
    monkeypatch.delenv("OFFLINE", raising=False)
    return TestClient(main.app)


def test_post_runs_the_trace_and_get_returns_the_case(client):
    r = client.post("/api/cases", json={"address": COINDCX, "case_ref": "FIR 12/2026"})
    assert r.status_code == 202 and r.headers["x-data-source"] == "live"
    queued = r.json()
    assert (queued["status"], queued["chain"], queued["outcome"]) == ("queued", "tron", None)

    r = client.get(f"/api/cases/{queued['id']}")
    assert r.status_code == 200 and r.headers["x-data-source"] == "live"
    case = r.json()
    S.CaseDetail.model_validate(case)
    assert (case["status"], case["outcome"], case["top_vasp"]) == ("done", "ATTRIBUTED", "CoinDCX")
    assert case["case_ref"] == "FIR 12/2026" and case["demo"] is False
    assert case["created_at"] == queued["created_at"]
    assert case["provenance"]["label_db_sha256"] and len(case["provenance"]["label_db_sha256"]) == 64
    assert case["provenance"]["data_sources"] == ["api.trongrid.io", "label store"]


def test_an_evm_address_is_traced_on_ethereum_and_stored_lowercase(client):
    r = client.post("/api/cases", json={"address": BITGET.upper().replace("0X", "0x")})
    assert r.status_code == 202 and r.json()["address"] == BITGET
    case = client.get(f"/api/cases/{r.json()['id']}").json()
    assert (case["chain"], case["top_vasp"]) == ("ethereum", "Bitget")


def test_max_hops_is_passed_to_the_trace(client):
    split = "TGfoGrh8ddh4zzpBe3G82p1tgmeUq49sWr"           # CoinDCX at 1 hop, HTX at 2 to 3
    cid = client.post("/api/cases", json={"address": split, "max_hops": 1}).json()["id"]
    case = client.get(f"/api/cases/{cid}").json()
    assert [c["vasp"] for c in case["candidates"]] == ["CoinDCX"]
    assert [s["kind"] for s in case["where_funds_went"]] == ["beyond_hop_limit", "vasp"]


def test_posting_the_same_wallet_again_returns_the_same_case_without_rerunning(client):
    first = client.post("/api/cases", json={"address": COINDCX}).json()
    done = client.get(f"/api/cases/{first['id']}").json()
    again = client.post("/api/cases", json={"address": COINDCX})
    assert again.status_code == 202
    assert (again.json()["id"], again.json()["status"]) == (first["id"], "done")
    assert client.get(f"/api/cases/{first['id']}").json() == done


def test_refresh_reruns_the_case(client):
    first = client.post("/api/cases", json={"address": COINDCX, "max_hops": 1}).json()
    r = client.post("/api/cases", params={"refresh": "true"}, json={"address": COINDCX})
    assert (r.json()["id"], r.json()["status"]) == (first["id"], "queued")
    assert client.get(f"/api/cases/{first['id']}").json()["outcome"] == "ATTRIBUTED"


def test_a_wallet_that_cannot_be_fetched_fails_with_a_readable_error(client, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "make_fetcher",
                        lambda: demo_fetcher(tmp_path / "empty.duckdb", offline=True))
    cid = client.post("/api/cases", json={"address": COINDCX}).json()["id"]
    case = client.get(f"/api/cases/{cid}").json()
    assert case["status"] == "failed" and case["outcome"] is None
    assert "OFFLINE=1" in case["error"] and "not cached" in case["error"]
    assert case["candidates"] == []
    # a failed case is retried by the next POST
    monkeypatch.setattr(main, "make_fetcher", lambda: demo_fetcher(tmp_path / "cache.duckdb"))
    client.post("/api/cases", json={"address": COINDCX})
    assert client.get(f"/api/cases/{cid}").json()["status"] == "done"


def test_a_refresh_that_fails_keeps_the_finished_case(client, tmp_path, monkeypatch):
    first = client.post("/api/cases", json={"address": COINDCX, "case_ref": "FIR 12/2026",
                                            "complaint_no": "315"}).json()
    good = client.get(f"/api/cases/{first['id']}").json()
    monkeypatch.setattr(main, "make_fetcher",
                        lambda: demo_fetcher(tmp_path / "empty.duckdb", offline=True))
    r = client.post("/api/cases", params={"refresh": "true"}, json={"address": COINDCX})
    assert r.json()["status"] == "queued"
    after = client.get(f"/api/cases/{first['id']}").json()
    assert (after["status"], after["outcome"], after["top_vasp"]) == ("done", "ATTRIBUTED", "CoinDCX")
    assert "Refresh failed" in after["error"] and "not cached" in after["error"]
    assert (after["case_ref"], after["complaint_no"]) == ("FIR 12/2026", "315")
    assert after["candidates"] == good["candidates"] and after["graph"] == good["graph"]


def test_a_refresh_keeps_the_case_details_unless_new_ones_are_given(client):
    first = client.post("/api/cases", json={"address": COINDCX, "case_ref": "FIR 12/2026",
                                            "complaint_no": "315"}).json()
    client.post("/api/cases", params={"refresh": "true"},
                json={"address": COINDCX, "complaint_no": "999"})
    case = client.get(f"/api/cases/{first['id']}").json()
    assert (case["status"], case["case_ref"], case["complaint_no"]) == ("done", "FIR 12/2026", "999")


@pytest.mark.parametrize("stuck", ["queued", "running"])
def test_a_case_left_unfinished_by_a_restart_is_run_again(client, tmp_path, stuck):
    from vaspfusion.cases import case_id_for, skeleton
    from vaspfusion.store.cases import CaseStore
    cid = case_id_for("tron", COINDCX)
    CaseStore(tmp_path / "case.duckdb").save(skeleton({
        "id": cid, "address": COINDCX, "chain": "tron", "status": stuck,
        "created_at": "2026-10-01T00:00:00Z", "case_ref": "FIR 7/2026"}))
    r = client.post("/api/cases", json={"address": COINDCX})
    assert r.json()["id"] == cid
    case = client.get(f"/api/cases/{cid}").json()
    assert (case["status"], case["top_vasp"], case["case_ref"]) == ("done", "CoinDCX", "FIR 7/2026")


@pytest.mark.parametrize("body,needle", [
    ({"address": "not-a-wallet"}, "chain"),
    ({"address": COINDCX, "chain": "ethereum"}, "not a valid ethereum address"),
    ({"address": "0x8894e0a0c962cb723c1976a4421c95949be2d4e3", "chain": "bsc"}, "bsc"),
    ({"address": "4Nd1mBQtrMJVYVfKf2PJy9NZUZdTAsp7D4xWLs4gDB4T"}, "solana"),
    ({"address": "1NBX1UZE3EFPTnYNkDfVhRADvVc8v6pRYu"}, "bitcoin"),
])
def test_addresses_we_cannot_trace_are_a_readable_422(client, body, needle):
    r = client.post("/api/cases", json=body)
    assert r.status_code == 422 and needle in r.json()["detail"]
    assert client.get("/api/cases").headers["x-data-source"] == "mock"     # nothing was stored


def test_list_shows_live_cases_before_the_mock_ones(client):
    assert client.get("/api/cases").headers["x-data-source"] == "mock"
    cid = client.post("/api/cases", json={"address": COINDCX}).json()["id"]
    r = client.get("/api/cases")
    assert r.headers["x-data-source"] == "mixed"
    items = r.json()["items"]
    assert items[0]["id"] == cid and items[0]["top_vasp"] == "CoinDCX"
    assert r.json()["total"] == len(items) == 4
    only = client.get("/api/cases", params={"outcome": "ATTRIBUTED"}).json()["items"]
    assert [c["id"] for c in only][0] == cid and all(c["outcome"] == "ATTRIBUTED" for c in only)


def test_mock_demo_cases_still_answer(client):
    r = client.get("/api/cases/demo-tron-okx")
    assert r.status_code == 200 and r.headers["x-data-source"] == "mock"


def test_the_wallet_page_lists_the_cases_a_wallet_appears_in(client):
    cid = client.post("/api/cases", json={"address": COINDCX}).json()["id"]
    # the trace ends at the customer's deposit address, a label derived in B4
    r = client.get("/api/wallets/tron/TCw8j3nQFnRDMUW2SeNbAgjnVKpELLcoV5")
    assert r.status_code == 200
    assert r.json()["cases"] == [{"case_id": cid, "role": "exchange_deposit", "hop": 1}]
    label = r.json()["labels"][0]
    assert (label["entity"], label["tier"], label["kind"]) == ("CoinDCX", "derived", "deposit")
    assert (label["confidence"], label["confidence_low"], label["confidence_high"]) == \
        (0.8491, 0.8491, 0.85)
    assert label["model"]["basis"] == "model" and len(label["model"]["reasons"]) == 3
    assert label["evidence"].startswith("Sweep rule: forwarded 100% of the 847,730 USDT")
    assert client.get(f"/api/wallets/tron/{COINDCX_2}").json()["cases"] == []

