"""The dashboard, the wallet page, label sources and the watchlist on the real pipeline:
the recorded demo wallets are traced, then the routes are read. No network."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demokit import SPECS, demo_fetcher, demo_label_db  # noqa: E402
from vaspfusion.api import main  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402
from vaspfusion.labels.sources import by_source, family  # noqa: E402


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
    return TestClient(main.app)


def _trace(client, *case_ids) -> list[str]:
    ids = []
    for cid in case_ids:
        r = client.post("/api/cases", json={"address": SPECS[cid]["address"],
                                            "chain": SPECS[cid]["chain"],
                                            "case_ref": SPECS[cid]["case_ref"]})
        assert r.status_code == 202
        ids.append(r.json()["id"])
    return ids


# ------------------------------------------------------------------ dashboard
def test_with_no_case_the_dashboard_is_the_fixture_with_live_label_counts(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200 and r.headers["x-data-source"] == "mixed"
    assert r.json()["counts"]["cases_total"] == 3
    assert r.json()["label_coverage"]["by_source"]


def test_the_dashboard_counts_the_stored_cases(client):
    ids = _trace(client, "tron-coindcx", "tron-htx-coindcx", "tron-ofac", "tron-abstain")
    r = client.get("/api/dashboard")
    assert r.status_code == 200 and r.headers["x-data-source"] == "live"
    d = S.Dashboard.model_validate(r.json())
    assert d.counts.cases_total == 4 and d.counts.tracing == 0 and d.counts.failed == 0
    assert d.outcomes == {"ATTRIBUTED": 2, "INSUFFICIENT_EVIDENCE": 1,
                          "SANCTIONED_OR_MIXER_REACHED": 1}
    assert [c.model_dump() for c in d.chain_mix] == [{"chain": "tron", "cases": 4}]
    desk = client.get("/api/desk").json()
    assert [(v.vasp, v.total_usd) for v in d.top_vasps] == [
        (row["vasp"], row["total_usd"]) for row in desk["rows"]]
    assert d.counts.open_cases == 2 and d.counts.awaiting_request == len(desk["rows"])
    assert d.attribution_times_n == 2 and d.median_time_to_attribution_s is not None
    assert any(a.case_id == ids[2] and "sanctioned" in a.text for a in d.recent_alerts)


def test_a_sent_request_is_counted_as_awaiting_a_reply(client):
    a, b = _trace(client, "tron-coindcx", "tron-htx-coindcx")
    made = client.post("/api/requests", json={
        "vasp": "CoinDCX", "case_ids": [a, b], "asks": ["kyc"],
        "officer": "Insp. A. Rao, Cyber PS"}).json()
    for status in ("approved", "sent"):
        assert client.patch(f"/api/requests/{made['id']}",
                            json={"status": status}).status_code == 200
    counts = client.get("/api/dashboard").json()["counts"]
    assert counts["requests_awaiting_reply"] == 1 and counts["awaiting_request"] == 1


# ------------------------------------------------------------------ wallet page
def test_the_wallet_page_reads_the_cases_the_wallet_is_in(client):
    cid, = _trace(client, "tron-ofac")
    addr = SPECS["tron-ofac"]["address"]
    w = S.WalletDetail.model_validate(client.get(f"/api/wallets/tron/{addr}").json())
    assert w.cases and w.flows_from_cases == 1 and w.watched is False
    assert w.outbound and w.outbound.tx_count >= 1 and w.outbound.asset == "USDT"
    assert w.risk.score == 100 and w.risk.risk_class == "severe" and w.risk.reasons
    assert w.risk.indicators[0].code == "sanctioned_contact" and "Not a probability" in w.risk.basis
    case = client.get(f"/api/cases/{cid}").json()
    hit = next(n["id"] for n in case["graph"]["nodes"] if n["role"] == "sanctioned")
    s = client.get(f"/api/wallets/tron/{hit}").json()
    assert s["risk"]["risk_class"] == "severe" and s["labels"][0]["category"] == "sanctioned"
    assert s["risk"]["indicators"][0]["code"] == "sanctioned_self"
    assert s["inbound"]["tx_count"] >= 1


def test_an_unknown_wallet_is_not_assessed(client):
    w = client.get("/api/wallets/tron/TGjpmhAFT6d7eBKvaFwPVN6H2pDKgLLZiw")
    assert w.status_code == 200
    assert w.json()["risk"]["risk_class"] is None and w.json()["risk"]["score"] is None
    assert w.json()["inbound"] is None


# ------------------------------------------------------------------ label sources
def test_label_coverage_names_each_source_and_never_guesses_a_licence(client):
    r = client.get("/api/labels/coverage")
    assert r.headers["x-data-source"] == "live"
    cov = S.LabelCoverage.model_validate(r.json())
    assert sum(s.labels for s in cov.by_source) == cov.total
    assert all(sum(s.tiers.values()) == s.labels for s in cov.by_source)


def test_source_families():
    assert family("graphsense-tagpack:exchange-wallets-bitmex_4") == "graphsense-tagpacks"
    assert family("cex-list+eth-labels") == "cex-list"
    assert family("etherscan public tag + dune-spellbook") == "dune-spellbook"
    assert family("somewhere else") == "somewhere else"
    rows = by_source([("eth-labels", "explorer_tag", 5), ("ofac-sdn+eth-labels", "curated", 2),
                      ("graphsense-tagpack:a", "curated", 3), ("graphsense-tagpack:b", "curated", 4),
                      ("unknown-set", "curated", 1)])
    by = {r["source"]: r for r in rows}
    assert [r["source"] for r in rows][0] == "graphsense-tagpacks"
    assert by["graphsense-tagpacks"]["labels"] == 7 and by["graphsense-tagpacks"]["licence"] == "MIT"
    assert by["eth-labels"]["licence"] is None            # upstream's own; not recorded here
    assert by["ofac-sdn"]["licence"] == "US-government public record"
    assert by["unknown-set"]["licence"] is None and by["unknown-set"]["obtained_from"] is None


# ------------------------------------------------------------------ watchlist
def test_watch_a_traced_wallet_check_it_and_stop(client):
    cid, = _trace(client, "tron-coindcx")
    addr = SPECS["tron-coindcx"]["address"]
    assert client.get("/api/watchlist").json() == {"items": []}
    made = client.post("/api/watchlist", json={"address": addr, "note": "  complainant's payee "})
    assert made.status_code == 201
    item = S.WatchItem.model_validate(made.json())
    assert item.state == "unchanged" and item.note == "complainant's payee"
    assert item.case_id == cid and item.baseline_at is not None
    assert client.post("/api/watchlist", json={"address": addr}).status_code == 409
    assert client.get(f"/api/wallets/tron/{addr}").json()["watched"] is True

    # the same recorded chain pages again: nothing is new
    again = client.post(f"/api/watchlist/{item.id}/check")
    assert again.status_code == 202
    listed = client.get("/api/watchlist").json()["items"]
    assert [w["state"] for w in listed] == ["unchanged"] and listed[0]["changes"] == []
    assert client.get("/api/dashboard").json()["counts"]["watched"] == 1

    assert client.post(f"/api/watchlist/{item.id}/seen").status_code == 200
    assert client.delete(f"/api/watchlist/{item.id}").json() == {"ok": True}
    assert client.delete(f"/api/watchlist/{item.id}").status_code == 404
    assert client.get("/api/watchlist").json() == {"items": []}


def test_a_change_since_the_baseline_reaches_the_list_and_the_dashboard(client):
    """The baseline is made older by taking the wallet's latest transfer and its exchange
    out of the stored snapshot; the trace itself is the real one."""
    _trace(client, "tron-coindcx")
    addr = SPECS["tron-coindcx"]["address"]
    item = client.post("/api/watchlist", json={"address": addr}).json()
    store = main._watch()
    entry = store.get(item["id"])
    entry["baseline"]["transfers"] = entry["baseline"]["transfers"][:-1]
    entry["baseline"]["exchanges"] = []
    store.save(entry)
    now = client.get("/api/watchlist").json()["items"][0]
    assert now["state"] == "changed"
    kinds = [c["kind"] for c in now["changes"]]
    assert "new_activity" in kinds and "new_exchange" in kinds
    alerts = client.get("/api/dashboard").json()["recent_alerts"]
    assert any(a["text"].startswith("Watched wallet: New exchange contact: CoinDCX") for a in alerts)
    seen = client.post(f"/api/watchlist/{item['id']}/seen").json()
    assert seen["state"] == "unchanged" and seen["changes"] == []


def test_watching_before_the_first_trace_and_bad_input(client):
    addr = SPECS["tron-abstain"]["address"]
    item = client.post("/api/watchlist", json={"address": addr}).json()
    assert item["state"] == "not_traced" and item["case_id"] is None
    assert client.post(f"/api/watchlist/{item['id']}/seen").status_code == 409
    assert client.post(f"/api/watchlist/{item['id']}/check").status_code == 202
    after = client.get("/api/watchlist").json()["items"][0]
    assert after["state"] == "unchanged" and after["case_id"] is not None   # its first trace is the baseline
    bad = client.post("/api/watchlist", json={"address": "TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1d"})
    assert bad.status_code == 422 and "Could not tell which chain" in bad.json()["detail"]
    assert client.post("/api/watchlist/tron-nope/check").status_code == 404
    assert client.delete("/api/watchlist/..%2f..").status_code in (404, 405)
    assert client.delete("/api/watchlist/tron-..").status_code == 404


# ------------------------------------------------------------------ threat tags (G3)
def test_a_case_is_screened_when_it_is_opened_and_names_the_threat_when_done(client):
    """Real wallet (demo/cases.json, tron-terror-link): 28% of its USDT went to two
    addresses the OFAC SDN list files under ISIL Khorasan, programmes FTO and SDGT."""
    spec = SPECS["tron-terror-link"]
    opened = client.post("/api/cases", json={"address": spec["address"], "chain": "tron"})
    assert opened.status_code == 202
    # the answer to the POST already carries the screening: the wallet itself is not listed
    assert opened.json()["screening"]["hit"] is False
    assert opened.json()["screening"]["text"].startswith("No direct hit")
    case = client.get(f"/api/cases/{opened.json()['id']}").json()
    assert case["status"] == "done" and case["threats"] == ["terrorism_financing"]
    flags = [f for f in case["typology_flags"] if f.get("threat")]
    assert [f["code"] for f in flags] == ["sanctioned_contact", "sanctioned_contact"]
    for f in flags:
        assert f["threat"]["threat"] == "terrorism_financing"
        assert f["threat"]["entity"] == "ISIL KHORASAN" and f["threat"]["source"] == "ofac-sdn-xml"
        assert "programme FTO, SDGT" in f["threat"]["evidence"]
        assert f["text"].endswith("tagged terrorism financing (ISIL KHORASAN, OFAC SDN list)")
        assert f["tx_hashes"]
    assert round(sum(f["figures"]["share"] for f in flags), 2) == 0.28

    # the cases list filters by threat, and the dashboard's alert carries the reason
    _trace(client, "tron-coindcx")
    listed = client.get("/api/cases", params={"threat": "terrorism_financing"}).json()["items"]
    assert [c["id"] for c in listed] == [case["id"]]
    assert client.get("/api/cases", params={"threat": "ransomware"}).json()["items"] == []
    alerts = client.get("/api/dashboard").json()["recent_alerts"]
    assert {a["threat"]["threat"] for a in alerts if a["case_id"] == case["id"]} == \
        {"terrorism_financing"}


def test_opening_a_case_on_a_listed_address_is_a_direct_hit_at_once(client):
    listed = "TLDtPq9PQsDuQunME8CSeVdYaLtRdrVgoJ"        # ISIL KHORASAN, OFAC SDN list
    with client:        # background tasks run inside the context; the POST answers first
        opened = client.post("/api/cases", json={"address": listed, "chain": "tron"}).json()
    assert opened["status"] == "queued"
    assert opened["screening"]["hit"] is True and opened["threats"] == ["terrorism_financing"]
    assert opened["screening"]["text"] == ("Direct hit: this address is tagged terrorism "
                                           "financing (ISIL KHORASAN, OFAC SDN list).")
    # the wallet page says the same, with the list entry's own words
    w = client.get(f"/api/wallets/tron/{listed}").json()
    assert w["risk"]["risk_class"] == "severe" and "uid 18647" in w["risk"]["reasons"][0]
    assert w["labels"][0]["threat"] == "terrorism_financing"


def test_label_search_and_coverage_know_the_threats(client):
    found = client.get("/api/labels/search", params={"threat": "terrorism_financing"}).json()
    assert found["total"] == 2 and {i["threat_entity"] for i in found["items"]} == \
        {"ISIL KHORASAN"}
    assert client.get("/api/labels/search", params={"threat": "nonsense"}).status_code == 422
    cover = client.get("/api/labels/coverage").json()
    assert cover["by_threat"]["terrorism_financing"] == 2
