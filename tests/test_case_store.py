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
                             "created_at", "demo", "error", "screening", "threats"}


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
    # each trace ends at a CoinDCX deposit address derived in B4, one hop from the suspect
    dep = store.wallet_cases("TCw8j3nQFnRDMUW2SeNbAgjnVKpELLcoV5", "tron")
    assert dep == [{"case_id": "tron-coindcx", "role": "exchange_deposit", "hop": 1}]
    htx = store.wallet_cases("TFTWNgDBkQ5wQoP8RXpRznnHvAVV8x5jLu", "tron")     # HTX reserves
    assert htx == [{"case_id": "tron-htx-coindcx", "role": "exchange", "hop": 2}]
    suspect = store.wallet_cases("TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c", "tron")
    assert suspect == [{"case_id": "tron-coindcx", "role": "suspect", "hop": 0}]
    assert store.wallet_cases("TU7BbAsb8t371eMijQeiGXsiLvY1vZbsFs", "ethereum") == []


def test_re_saving_a_case_does_not_duplicate_its_wallets(store, tmp_path):
    case = run_demo("tron-coindcx", tmp_path / "a.duckdb")
    store.save(case)
    store.save(case)
    assert len(store.wallet_cases("TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c", "tron")) == 1


def test_writers_on_several_threads_do_not_collide(store):
    import threading
    errors = []

    def hammer(n):
        try:
            for i in range(25):
                store.save({**queued(), "status": "running" if (n + i) % 2 else "queued"})
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=hammer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(store.list()) == 1


def test_a_wallet_reached_over_a_bridge_is_found_on_its_own_chain(store, tmp_path):
    """Real: the eth-bridge wallet's money came out on Base at the same address."""
    case = run_demo("eth-bridge", tmp_path / "c.duckdb")
    store.save(case)
    me = case["address"]
    assert [(r["role"], r["hop"]) for r in store.wallet_cases(me, "ethereum")] == [("suspect", 0)]
    assert [(r["role"], r["hop"]) for r in store.wallet_cases(me, "base")] == [("intermediary", 2)]
    assert store.wallet_cases(f"base:{me}", "base") == []
