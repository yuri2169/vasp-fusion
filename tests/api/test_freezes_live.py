"""The issuer's freeze marks on the live routes, from the tracked snapshot
(data/usdt_frozen.csv) and a recorded case: the sanctioned Tron wallet's money reached
an address Tether froze. Replays the recorded demo wallets; no network."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demokit import SPECS, demo_fetcher, demo_label_db  # noqa: E402
from vaspfusion.api import main  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402
from vaspfusion.labels.frozen import FreezeList  # noqa: E402

OFAC = SPECS["tron-ofac"]["address"]
pytestmark = pytest.mark.skipif(FreezeList.load().stats()["total"] == 0,
                                reason="no freeze snapshot (make frozen)")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "LABEL_DB", demo_label_db(tmp_path / "labels.duckdb"))
    monkeypatch.setattr(main, "CASE_DB", tmp_path / "case.duckdb")
    monkeypatch.setattr(main, "make_fetcher", lambda: demo_fetcher(tmp_path / "cache.duckdb"))
    monkeypatch.setenv("ETHERSCAN_API_KEY", "test-key")
    monkeypatch.setenv("TRONGRID_API_KEY", "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")
    monkeypatch.delenv("OFFLINE", raising=False)
    return TestClient(main.app)


def test_a_served_case_marks_the_frozen_wallet_on_its_path_and_counts_it(client):
    cid = client.post("/api/cases", json={"address": OFAC}).json()["id"]
    case = client.get(f"/api/cases/{cid}").json()
    S.CaseDetail.model_validate(case)
    path = [m for m in case["freezes"] if m["where"] == "path"]
    assert len(path) == 1 and path[0]["side"] == "outbound" and path[0]["hop"] == 1
    assert path[0]["text"].startswith("Frozen by Tether on ")
    assert path[0]["address"] in {h["to_address"] for h in case["hop_rail"]}
    assert path[0]["tx_hashes"] and path[0]["amount"] > 0
    codes = {i["code"] for i in case["risk"]["indicators"]}
    assert "frozen_contact" in codes and "sanctioned_contact" in codes
    assert case["risk"]["risk_class"] == "severe"         # it was Severe already


def test_opening_a_case_on_a_frozen_address_screens_it_at_once(client):
    cid = client.post("/api/cases", json={"address": OFAC}).json()["id"]
    frozen = next(m for m in client.get(f"/api/cases/{cid}").json()["freezes"]
                  if m["where"] == "path")["address"]
    r = client.post("/api/cases", json={"address": frozen, "chain": "tron"})
    assert r.status_code == 202
    assert r.json()["freeze"]["where"] == "origin"
    assert r.json()["freeze"]["issuer"] == "Tether"
    wallet = client.get(f"/api/wallets/tron/{frozen}").json()
    assert wallet["freeze"]["frozen_at"].startswith(
        FreezeList.load().lookup(frozen, "tron")["frozen_at"][:10])
    assert "frozen_self" in {i["code"] for i in wallet["risk"]["indicators"]}


def test_a_case_with_no_frozen_wallet_has_none(client):
    cid = client.post("/api/cases", json={"address": SPECS["tron-coindcx"]["address"]}).json()["id"]
    assert client.get(f"/api/cases/{cid}").json()["freezes"] == []
    assert client.post("/api/cases", json={"address": SPECS["tron-coindcx"]["address"]}).json()[
        "freeze"] is None


def test_the_list_is_counted_apart_and_searchable(client):
    cov = client.get("/api/labels/coverage").json()["frozen"]
    st = FreezeList.load().stats()
    assert cov["total"] == st["total"] and cov["by_chain"] == st["by_chain"]
    assert "does not say why" in cov["meaning"] and "isBlackListed" in cov["check"]
    r = client.get("/api/labels/frozen", params={"chain": "ethereum", "limit": 3}).json()
    assert r["total"] == st["by_chain"]["ethereum"] and len(r["items"]) == 3
    assert all(i["chain"] == "ethereum" and i["issuer"] == "Tether" for i in r["items"])
    one = r["items"][0]["address"]
    assert client.get("/api/labels/frozen", params={"q": one[2:12]}).json()["total"] >= 1
