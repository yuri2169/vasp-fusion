"""The wallet page's figures and the watchlist's changes, on real demo cases (the
interface's fixtures). A "before" trace is made by taking transfers, an exchange or a
flag away from a real case, never by inventing one."""
import copy
import json
from pathlib import Path

import pytest

from vaspfusion.store.watch import WatchStore, watch_id
from vaspfusion.wallets import wallet_view
from vaspfusion.watch import alerts_of, changes, snapshot, watch_item

FIXTURES = Path(__file__).resolve().parents[1] / "ui" / "src" / "test" / "fixtures" / "cases"


def case(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(scope="module")
def ofac():
    return case("tron-ofac")


@pytest.fixture(scope="module")
def hero():
    return case("tron-coindcx")


# ------------------------------------------------------------------ wallet page
def test_outbound_of_the_traced_wallet_is_what_the_case_read(hero):
    v = wallet_view(hero["address"], "tron", [hero], None)
    out = [e for e in hero["graph"]["edges"] if e["source"] == hero["address"]]
    assert v["outbound"]["tx_count"] == len(out)
    assert v["outbound"]["asset"] == "USDT"
    assert v["outbound"]["total"] == pytest.approx(sum(e["amount"] for e in out))
    assert v["outbound"]["first_seen"] <= v["outbound"]["last_seen"]
    assert v["outbound"]["counterparties"] == len({e["target"] for e in out})
    assert set(v["outbound"]["top_counterparties"]) <= {e["target"] for e in out}
    assert v["flows_from_cases"] == 1


def test_a_transfer_read_by_two_cases_counts_once(hero):
    once = wallet_view(hero["address"], "tron", [hero], None)
    twice = wallet_view(hero["address"], "tron", [hero, {**hero, "id": "again"}], None)
    assert twice["outbound"] == once["outbound"] and twice["flows_from_cases"] == 2


def test_a_wallet_in_no_case_and_unlabelled_is_not_assessed():
    v = wallet_view("TXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX", "tron", [], None)
    assert (v["risk"]["score"], v["risk"]["risk_class"], v["risk"]["reasons"]) == (None, None, [])
    assert v["inbound"] is None and v["outbound"] is None


def test_a_sanctioned_address_is_high_with_its_label_and_the_flag(ofac):
    node = next(n for n in ofac["graph"]["nodes"] if n["role"] == "sanctioned")
    v = wallet_view(node["id"], "tron", [ofac], node["label"])
    assert v["risk"]["risk_class"] == "severe" and v["risk"]["score"] == 100
    assert "sanctions list" in v["risk"]["reasons"][0] and "ofac-sdn" in v["risk"]["reasons"][0]
    assert v["inbound"]["tx_count"] >= 1 and v["outbound"] is None


def test_the_wallet_that_paid_a_sanctioned_address_is_severe(ofac):
    v = wallet_view(ofac["address"], "tron", [ofac], None)
    assert v["risk"]["risk_class"] == "severe"
    assert "reached a sanctioned address" in v["risk"]["reasons"][0]
    flag = next(f for f in ofac["typology_flags"] if f["code"] == "sanctioned_contact")
    assert v["risk"]["reasons"][0].endswith(flag["text"])


def test_a_clean_traced_wallet_has_nothing_on_record(hero):
    quiet = {**hero, "typology_flags": [f for f in hero["typology_flags"]
                                        if f["wallet"] != hero["address"]]}
    v = wallet_view(hero["address"], "tron", [quiet], None)
    quiet["where_funds_went"] = [s for s in quiet["where_funds_went"] if s["kind"] != "hub"]
    quiet["typology_flags"] = []
    v = wallet_view(hero["address"], "tron", [quiet], None)
    assert (v["risk"]["risk_class"], v["risk"]["score"], v["risk"]["reasons"]) == ("low", 0, [])


# ------------------------------------------------------------------ watchlist
def _entry(c: dict, baseline: dict | None) -> dict:
    return {"id": watch_id(c["chain"], c["address"]), "chain": c["chain"],
            "address": c["address"], "note": None, "added_at": "2026-10-04T00:00:00Z",
            "added_by": None, "baseline": baseline}


def test_the_same_trace_shows_no_change(hero):
    assert changes(snapshot(hero), hero) == []
    item = watch_item(_entry(hero, snapshot(hero)), hero)
    assert item["state"] == "unchanged" and item["changes"] == []
    # a replay from the cache has no fetch time: the day the case was traced stands in
    assert item["last_checked_at"] == (hero["provenance"]["fetched_at"] or hero["created_at"])


def test_new_transfers_are_counted_from_the_baseline(hero):
    before = copy.deepcopy(hero)
    own = [e for e in before["graph"]["edges"] if hero["address"] in (e["source"], e["target"])]
    gone = sorted(own, key=lambda e: e["block_time"])[-1]
    before["graph"]["edges"] = [e for e in before["graph"]["edges"]
                                if e["tx_hash"] != gone["tx_hash"]]
    found = changes(snapshot(before), hero)
    activity = [c for c in found if c["kind"] == "new_activity"]
    assert len(activity) == 1 and activity[0]["text"].startswith("1 new transfer of this wallet")
    assert watch_item(_entry(hero, snapshot(before)), hero)["state"] == "changed"


def test_a_new_exchange_and_a_new_alert_are_named(ofac, hero):
    before = {**hero, "candidates": [c for c in hero["candidates"] if c["vasp"] != "CoinDCX"]}
    found = changes(snapshot(before), hero)
    assert [c["text"] for c in found if c["kind"] == "new_exchange"] == [
        "New exchange contact: CoinDCX was reached, 1 hop away"]
    quiet = {**ofac, "typology_flags": [f for f in ofac["typology_flags"]
                                        if f["severity"] != "high"]}
    found = changes(snapshot(quiet), ofac)
    alert = next(c for c in found if c["kind"] == "new_alert")
    assert alert["severity"] == "high" and "sanctioned" in alert["text"]
    item = watch_item(_entry(ofac, snapshot(quiet)), ofac)
    assert alerts_of(item)[0]["text"].startswith("Watched wallet: New alert:")
    rise = next(c for c in found if c["kind"] == "risk_raised")
    assert rise["severity"] == "high"
    assert rise["text"] == ("Risk class rose from Low to Severe: funds reached a sanctioned "
                            "address")
    assert item["risk_class"] == "severe"
    # a baseline taken before risk classes existed is not a rise, and a fall is not news
    old = {k: v for k, v in snapshot(quiet).items() if k != "risk_class"}
    assert not [c for c in changes(old, ofac) if c["kind"] == "risk_raised"]
    assert not [c for c in changes(snapshot(ofac), quiet) if c["kind"] == "risk_raised"]
    assert alerts_of(item)[0]["case_id"] == "tron-ofac"


def test_states_without_a_finished_case(hero):
    e = _entry(hero, None)
    assert watch_item(e, None)["state"] == "not_traced"
    assert watch_item(e, None, tracing=True)["state"] == "checking"
    assert watch_item(e, {**hero, "status": "running"})["state"] == "checking"
    failed = {"id": hero["id"], "status": "failed", "error": "CacheMiss: not cached",
              "created_at": hero["created_at"]}
    item = watch_item(e, failed)
    assert item["state"] == "failed" and item["error"] == "CacheMiss: not cached"
    # a wallet added before its first trace: the first result is the baseline, not news
    assert watch_item(e, hero)["changes"] == []


def test_the_store_keeps_and_removes_entries(tmp_path, hero):
    store = WatchStore(tmp_path / "watch.duckdb")
    e = _entry(hero, snapshot(hero))
    store.save(e)
    store.save({**e, "note": "second look"})
    assert [w["note"] for w in store.list()] == ["second look"]
    assert store.get(e["id"])["baseline"]["case_id"] == hero["id"]
    assert store.remove(e["id"]) is True and store.remove(e["id"]) is False
    assert store.list() == []


# ------------------------------------------------------------------ threat tags (G3)
TAG = {"threat": "ransomware", "entity": "Conti", "source": "ransomwhere", "url": None,
       "evidence": "Ransomwhere: ransomware payment address, family Conti."}


def test_a_tagged_address_is_high_risk_with_the_source_s_words():
    from vaspfusion.wallets import wallet_view
    label = {"category": "entity", "entity": "Conti", "source": "ransomwhere", "label": "Conti",
             "threat": "ransomware", "threat_entity": "Conti", "threat_source": "ransomwhere",
             "threat_url": None, "threat_evidence": TAG["evidence"]}
    risk = wallet_view("RW", "tron", [], label)["risk"]
    assert (risk["risk_class"], risk["indicators"][0]["code"]) == ("severe", "threat_self")
    assert risk["reasons"] == ["This address is tagged ransomware (Conti, Ransomwhere). "
                               "Ransomwhere: ransomware payment address, family Conti."]


def _case_with(flags):
    return {"id": "c-1", "address": "S", "created_at": "2026-10-05T00:00:00Z",
            "graph": {"edges": []}, "candidates": [], "typology_flags": flags,
            "outcome": "INSUFFICIENT_EVIDENCE", "status": "done"}


def test_a_recheck_that_finds_a_new_link_to_a_tagged_address_is_a_high_change():
    from vaspfusion.watch import alerts_of, changes, snapshot
    flag = {"code": "threat_contact", "severity": "high", "wallet": "RW", "threat": TAG,
            "text": "Linked to ransomware (Conti, Ransomwhere): 2 hops away, 14% of the funds "
                    "(140 USDT) reached RW"}
    before = snapshot(_case_with([]))
    assert before["threat_links"] == []
    found = changes(before, _case_with([flag]))
    # not also a "new alert"; the rise in risk class the link caused is said once, after it
    assert [c["kind"] for c in found] == ["new_threat_link", "risk_raised"]
    assert found[1]["text"] == ("Risk class rose from Low to Severe: funds reached a "
                                "threat-tagged address")
    assert found[0]["severity"] == "high" and found[0]["threat"] == TAG
    assert found[0]["text"].startswith("New link to a tagged address: Linked to ransomware")
    assert changes(snapshot(_case_with([flag])), _case_with([flag])) == []
    alert, _rise = alerts_of({"address": "S", "chain": "tron", "case_id": "c-1",
                              "changes": found})
    assert alert["threat"] == TAG and alert["severity"] == "high"


def test_a_baseline_taken_before_threat_tags_raises_no_link_as_new():
    from vaspfusion.watch import changes, snapshot
    flag = {"code": "sanctioned_contact", "severity": "high", "wallet": "X", "threat": TAG,
            "text": "t"}
    old = snapshot(_case_with([flag]))
    del old["threat_links"]
    assert changes(old, _case_with([flag])) == []


def test_screening_says_hit_or_no_hit_in_one_sentence():
    from vaspfusion.screening import case_threats, screen
    hit = screen({"category": "entity", "entity": "Conti", "source": "ransomwhere",
                  "threat": "ransomware", "threat_entity": "Conti",
                  "threat_source": "ransomwhere"})
    assert hit["hit"] and hit["tag"]["threat"] == "ransomware"
    assert hit["text"] == "Direct hit: this address is tagged ransomware (Conti, Ransomwhere)."
    mixer = screen({"category": "mixer", "entity": "Tornado Cash", "source": "eth-labels"})
    assert mixer["hit"] and mixer["tag"] is None and "labelled a mixer" in mixer["text"]
    assert screen(None)["hit"] is False and screen({"category": "exchange"})["hit"] is False
    assert case_threats(None, [{"threat": {"threat": "fraud"}}, {},
                               {"threat": {"threat": "ransomware"}}]) == ["ransomware", "fraud"]
