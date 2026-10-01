"""Cases persist in DuckDB: the whole CaseDetail, plus the wallets it touched."""
from datetime import datetime, timezone

import pytest

from demokit import run_demo
from vaspfusion.cases import skeleton
from vaspfusion.store.cases import CaseStore


def queued(case_id="c-1", address="TADDR", minute=0, **extra):
    return skeleton({"id": case_id, "address": address, "chain": "tron", "status": "queued",
                     "created_at": datetime(2026, 10, 1, 12, minute, tzinfo=timezone.utc)
                     .isoformat().replace("+00:00", "Z"), **extra})


@pytest.fixture
def store(tmp_path):
    return CaseStore(tmp_path / "case.duckdb")


def test_a_saved_case_comes_back_whole(store, tmp_path):
    case = run_demo("tron-coindcx", tmp_path / "cache.duckdb")
    store.save(case)
    assert store.get("tron-coindcx") == case
    assert store.get("nope") is None


def test_saving_again_replaces_the_case(store):
    store.save(queued())
    store.save({**queued(), "status": "running"})
    assert store.get("c-1")["status"] == "running"
    assert len(store.list()) == 1


def test_list_is_newest_first_summaries(store, tmp_path):
    store.save(queued("c-old", minute=0))
    store.save(run_demo("tron-ofac", tmp_path / "cache.duckdb",
                        now=datetime(2026, 10, 1, 12, 30, tzinfo=timezone.utc)))
    store.save(queued("c-new", minute=59))
    items = store.list()
    assert [c["id"] for c in items] == ["c-new", "tron-ofac", "c-old"]
    assert "graph" not in items[1] and items[1]["outcome"] == "SANCTIONED_OR_MIXER_REACHED"
    assert set(items[1]) == {"id", "address", "chain", "status", "outcome", "top_vasp",
                             "confidence", "case_ref", "complaint_no", "amount_lost_inr",
                             "created_at", "demo", "error"}


def test_list_filters_by_outcome_and_status(store, tmp_path):
    store.save(queued("c-q"))
    store.save(run_demo("tron-ofac", tmp_path / "cache.duckdb"))
    assert [c["id"] for c in store.list(status="queued")] == ["c-q"]
    assert [c["id"] for c in store.list(outcome="SANCTIONED_OR_MIXER_REACHED")] == ["tron-ofac"]
    assert store.list(outcome="ATTRIBUTED") == []


def test_status_changes_keep_the_rest(store):
    store.save(queued(case_ref="FIR 1/2026"))
    store.set_status("c-1", "failed", error="OFFLINE=1 and not cached")
    case = store.get("c-1")
    assert (case["status"], case["error"], case["case_ref"]) == \
        ("failed", "OFFLINE=1 and not cached", "FIR 1/2026")


def test_the_file_survives_reopening(tmp_path):
    path = tmp_path / "case.duckdb"
    CaseStore(path).save(queued())
    assert CaseStore(path).get("c-1")["status"] == "queued"


def test_wallets_point_back_to_their_cases(store, tmp_path):
    store.save(run_demo("tron-coindcx", tmp_path / "a.duckdb"))
    store.save(run_demo("tron-htx-coindcx", tmp_path / "b.duckdb"))
    hot = store.wallet_cases("TU7BbAsb8t371eMijQeiGXsiLvY1vZbsFs", "tron")     # CoinDCX 2
    assert hot == [{"case_id": "tron-coindcx", "role": "exchange", "hop": 2},
                   {"case_id": "tron-htx-coindcx", "role": "exchange", "hop": 2}]
    suspect = store.wallet_cases("TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c", "tron")
    assert suspect == [{"case_id": "tron-coindcx", "role": "suspect", "hop": 0}]
    assert store.wallet_cases("TU7BbAsb8t371eMijQeiGXsiLvY1vZbsFs", "ethereum") == []


def test_re_saving_a_case_does_not_duplicate_its_wallets(store, tmp_path):
    case = run_demo("tron-coindcx", tmp_path / "a.duckdb")
    store.save(case)
    store.save(case)
    assert len(store.wallet_cases("TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c", "tron")) == 1
