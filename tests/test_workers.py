"""Worker processes on the real pipeline: several of them drain one queue, every wallet
is traced exactly once, a case is the same whoever traced it, and a worker that dies
mid-trace loses nothing. Recorded demo wallets, replayed from a cache file; no network."""
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from demokit import SPECS, demo_fetcher, demo_label_db, run_demo
from vaspfusion.api import schemas as S
from vaspfusion.cases import skeleton
from vaspfusion.store.cases import CaseStore
from vaspfusion.store.queue import JobQueue
from vaspfusion.workers import WorkerPool

ROOT = Path(__file__).resolve().parents[1]
WALLETS = ("tron-coindcx", "eth-bitget", "tron-ofac", "eth-abstain", "polygon-bitget", "sol-okx")


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    """A cache file holding the pages of the wallets above, their label DB, and the
    fingerprint each case has when it is traced in this process."""
    home = tmp_path_factory.mktemp("workers")
    cache = home / "cache.duckdb"
    expected = {w: run_demo(w, cache)["provenance"]["findings_sha256"] for w in WALLETS}
    demo_fetcher(cache, offline=True).close()
    return {"cache": cache, "labels": demo_label_db(home / "labels.duckdb"),
            "expected": expected}


def env_for(recorded, case_db) -> dict:
    return {**os.environ, "OFFLINE": "1", "ETHERSCAN_API_KEY": "test-key",
            "TRONGRID_API_KEY": "test-key", "VASPFUSION_AUTH": "off",
            "VASPFUSION_CHAIN_CACHE": str(recorded["cache"]),
            "VASPFUSION_LABEL_DB": str(recorded["labels"]),
            "VASPFUSION_CASE_DB": str(case_db),
            "VASPFUSION_DESK_DB": str(case_db.parent / "desk.duckdb"),
            "VASPFUSION_SAHYOG_OUTBOX": str(case_db.parent / "outbox")}


def queue_up(case_db, rounds: int = 1) -> list[str]:
    store, queue, ids = CaseStore(case_db), JobQueue(case_db), []
    now = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
    for n in range(rounds):
        for w in WALLETS:
            spec = SPECS[w]
            cid = f"{w}-{n}"
            store.save(skeleton(S.CaseSummary(
                id=cid, address=spec["address"], chain=spec["chain"], status="queued",
                created_at=now, screening={"hit": False, "text": "-"}).model_dump(mode="json")))
            queue.enqueue(cid, {"max_hops": spec["max_hops"]})
            ids.append(cid)
    return ids


def test_three_workers_drain_the_queue_and_each_wallet_is_traced_once(recorded, tmp_path):
    case_db = tmp_path / "case.duckdb"
    ids = queue_up(case_db, rounds=2)
    pool = WorkerPool(3, env=env_for(recorded, case_db), drain=True).start()
    assert pool.wait(timeout=180) == [0, 0, 0]

    jobs = JobQueue(case_db).finished()
    assert sorted(j["case_id"] for j in jobs) == sorted(ids)
    assert all(j["state"] == "done" and j["attempts"] == 1 for j in jobs), \
        [(j["case_id"], j["state"], j["error"]) for j in jobs if j["state"] != "done"]
    assert len({j["worker"] for j in jobs}) >= 2          # the work was shared
    assert all(j["stats"]["seconds"] > 0 and j["stats"]["pages"] > 0 for j in jobs)

    store = CaseStore(case_db)
    for cid in ids:
        case = store.get(cid)
        S.CaseDetail.model_validate(case)
        assert case["status"] == "done"
        # the same findings as the trace made in this process
        assert case["provenance"]["findings_sha256"] == recorded["expected"][cid.rsplit("-", 1)[0]]
        assert case["provenance"]["offline_replay"] is True


_SLOW_WORKER = """
import os, sys, time
from vaspfusion.api import main as api
from vaspfusion.store.queue import worker_name
api.LABEL_DB = os.environ["VASPFUSION_LABEL_DB"]
real = api.run_case
def slow(*a, **k):
    print("claimed", flush=True)
    time.sleep(120)
    return real(*a, **k)
api.run_case = slow
api.work_one(worker=worker_name(9))
"""


def test_a_worker_killed_mid_trace_loses_nothing(recorded, tmp_path):
    case_db = tmp_path / "case.duckdb"
    env = env_for(recorded, case_db)
    ids = queue_up(case_db)
    doomed = subprocess.Popen([sys.executable, "-c", _SLOW_WORKER], cwd=ROOT, env=env,
                              stdout=subprocess.PIPE, text=True)
    assert doomed.stdout.readline().strip() == "claimed"
    queue = JobQueue(case_db)
    held = [j for j in map(queue.get, ids) if j["state"] == "running"]
    assert len(held) == 1 and CaseStore(case_db).get(held[0]["case_id"])["status"] == "running"
    doomed.send_signal(signal.SIGKILL)
    doomed.wait()

    pool = WorkerPool(2, env=env, drain=True).start()
    assert pool.wait(timeout=180) == [0, 0]
    jobs = {j["case_id"]: j for j in queue.finished()}
    assert sorted(jobs) == sorted(ids) and all(j["state"] == "done" for j in jobs.values())
    assert jobs[held[0]["case_id"]]["attempts"] == 2      # claimed again after the crash
    assert all(CaseStore(case_db).get(cid)["status"] == "done" for cid in ids)


def test_the_pool_restarts_a_worker_that_exits_and_stops_with_the_server(recorded, tmp_path):
    case_db = tmp_path / "case.duckdb"
    pool = WorkerPool(2, env=env_for(recorded, case_db)).start()
    try:
        assert pool.alive() == 2
        first = pool.procs[0]
        first.kill()
        first.wait()
        deadline = time.monotonic() + 20
        while pool.procs[0] is first and time.monotonic() < deadline:
            time.sleep(0.2)
        assert pool.procs[0] is not first and pool.alive() == 2
        ids = queue_up(case_db)                 # work that arrives later is still picked up
        deadline = time.monotonic() + 120
        while JobQueue(case_db).counts()["done"] < len(ids) and time.monotonic() < deadline:
            time.sleep(0.3)
        assert JobQueue(case_db).counts() == {"queued": 0, "running": 0, "done": len(ids),
                                              "failed": 0}
    finally:
        pool.stop()
    assert pool.alive() == 0


def test_a_running_trace_in_a_worker_shows_its_progress_through_the_queue(recorded, tmp_path,
                                                                        monkeypatch):
    from fastapi.testclient import TestClient

    from vaspfusion.api import main
    case_db = tmp_path / "case.duckdb"
    monkeypatch.setattr(main, "CASE_DB", case_db)
    monkeypatch.setattr(main, "LABEL_DB", recorded["labels"])
    monkeypatch.setattr(main, "WORKERS", 2)     # this server leaves tracing to workers
    client = TestClient(main.app)
    r = client.post("/api/cases", json={"address": SPECS["tron-coindcx"]["address"]})
    cid = r.json()["id"]
    assert r.status_code == 202 and main._queue().queued_ids() == [cid]   # queued, not run here
    assert client.get(f"/api/cases/{cid}").json()["status"] == "queued"
    again = client.post("/api/cases", json={"address": SPECS["tron-coindcx"]["address"]})
    assert again.json()["id"] == cid and main._queue().counts()["queued"] == 1

    # a worker has claimed it and reported what it read so far
    queue = main._queue()
    queue.claim("elsewhere:1:0")
    main._cases().set_status(cid, "running")
    queue.beat(cid, "elsewhere:1:0", progress={
        "phase": "outbound", "asset": "USDT", "hop": 1, "wallets_read": 2,
        "transfers_read": 31, "reached": []})
    case = client.get(f"/api/cases/{cid}").json()
    assert case["progress"]["wallets_read"] == 2
    assert "31 USDT transfers of 2 wallets" in case["progress"]["message"]

    # that worker goes silent; the job is queued again and a real worker finishes it
    monkeypatch.setattr(queue, "lease_s", -1.0)
    assert queue.requeue_stale() == ([cid], [])
    pool = WorkerPool(1, env=env_for(recorded, case_db), drain=True).start()
    assert pool.wait(timeout=120) == [0]
    done = client.get(f"/api/cases/{cid}").json()
    assert (done["status"], done["top_vasp"], done["progress"]) == ("done", "CoinDCX", None)
    assert json.dumps(done)                      # (a full, serialisable case)
