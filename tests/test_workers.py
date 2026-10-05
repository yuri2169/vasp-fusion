"""The worker pool on the real pipeline: several processes drain one queue, every wallet
is traced exactly once, a case is the same whoever traced it, and a process that dies
mid-trace loses nothing. Recorded demo wallets, replayed from a cache file; no network."""
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from demokit import SPECS, demo_fetcher, demo_label_db, run_demo
from vaspfusion.api import main
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


@pytest.fixture
def home(recorded, tmp_path, monkeypatch):
    """This process as the server that owns a fresh case store; worker processes read
    the recorded cache through the environment they inherit."""
    for name, value in {"OFFLINE": "1", "ETHERSCAN_API_KEY": "test-key",
                        "TRONGRID_API_KEY": "test-key",
                        "VASPFUSION_CHAIN_CACHE": str(recorded["cache"])}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(main, "CASE_DB", tmp_path / "case.duckdb")
    monkeypatch.setattr(main, "DESK_DB", tmp_path / "desk.duckdb")
    monkeypatch.setattr(main, "OUTBOX", tmp_path / "outbox")
    monkeypatch.setattr(main, "LABEL_DB", recorded["labels"])
    yield tmp_path / "case.duckdb"
    main.stop_pool()


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


def test_three_workers_drain_the_queue_and_each_wallet_is_traced_once(recorded, home,
                                                                    monkeypatch):
    seen: list[tuple[str, str]] = []
    real = main._note_progress
    monkeypatch.setattr(main, "_note_progress",
                        lambda cid, p: (seen.append((cid, p["phase"])), real(cid, p)))
    ids = queue_up(home, rounds=2)
    pool = main.start_pool(3)
    assert pool.drain(timeout=180)

    jobs = JobQueue(home).finished()
    assert sorted(j["case_id"] for j in jobs) == sorted(ids)
    assert all(j["state"] == "done" and j["attempts"] == 1 for j in jobs), \
        [(j["case_id"], j["state"], j["error"]) for j in jobs if j["state"] != "done"]
    pids = {j["stats"]["pid"] for j in jobs}
    assert len(pids) >= 2 and os.getpid() not in pids        # traced in the workers
    assert all(j["stats"]["seconds"] > 0 and j["stats"]["pages"] > 0 for j in jobs)

    store = CaseStore(home)
    for cid in ids:
        case = store.get(cid)
        S.CaseDetail.model_validate(case)
        assert case["status"] == "done"
        # the same findings as the trace made in this process
        assert case["provenance"]["findings_sha256"] == recorded["expected"][cid.rsplit("-", 1)[0]]
        assert case["provenance"]["offline_replay"] is True
    # the workers' progress reached this process, and nothing of it is left behind
    assert {cid for cid, phase in seen if phase == "checking"} == set(ids)
    assert main._PROGRESS == {} and main._ACTIVE == set()


def test_the_pool_lets_go_of_the_store_when_the_queue_is_empty(home):
    ids = queue_up(home)
    pool = main.start_pool(2)
    assert pool.drain(timeout=180)
    deadline = time.monotonic() + 10
    while pool._anchor is not None and time.monotonic() < deadline:
        time.sleep(0.1)
    assert pool._anchor is None
    # another process can now open the case store (the command line, between batches)
    out = subprocess.run(
        [sys.executable, "-c", "import sys; from vaspfusion.store.cases import CaseStore; "
         "print(len(CaseStore(sys.argv[1]).list()))", str(home)],
        cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == str(len(ids)), out.stderr[-300:]


def test_a_worker_process_that_dies_loses_nothing(home):
    ids = queue_up(home, rounds=2)
    pool = main.start_pool(2)
    deadline = time.monotonic() + 60
    while not pool._inflight and time.monotonic() < deadline:
        time.sleep(0.005)
    for pid in pool.worker_pids():              # every worker, with jobs in flight
        os.kill(pid, signal.SIGKILL)
    assert pool.drain(timeout=180)
    jobs = {j["case_id"]: j for j in JobQueue(home).finished()}
    assert sorted(jobs) == sorted(ids)
    assert all(j["state"] == "done" for j in jobs.values()), \
        [(j["case_id"], j["error"]) for j in jobs.values() if j["state"] != "done"]
    assert max(j["attempts"] for j in jobs.values()) >= 2      # something was taken again
    assert all(CaseStore(home).get(cid)["status"] == "done" for cid in ids)
    assert set(pool.worker_pids()) and main._ACTIVE == set()


_DYING_SERVER = """
import os, sys, time
from vaspfusion.api import main as api
api.LABEL_DB = sys.argv[1]
real = api.run_case
def slow(*a, **k):
    print("claimed", flush=True)
    time.sleep(120)
    return real(*a, **k)
api.run_case = slow
api.work_one()
"""


def test_a_server_killed_mid_trace_loses_nothing(recorded, home):
    ids = queue_up(home)
    env = {**os.environ, "VASPFUSION_CASE_DB": str(home)}
    doomed = subprocess.Popen([sys.executable, "-c", _DYING_SERVER, str(recorded["labels"])],
                              cwd=ROOT, env=env, stdout=subprocess.PIPE, text=True)
    assert doomed.stdout.readline().strip() == "claimed"
    queue = JobQueue(home)
    held = [j for j in map(queue.get, ids) if j["state"] == "running"]
    assert len(held) == 1 and CaseStore(home).get(held[0]["case_id"])["status"] == "running"
    doomed.send_signal(signal.SIGKILL)
    doomed.wait()

    assert main.recover() == ([held[0]["case_id"]], [])    # what a server does when it starts
    pool = main.start_pool(2)
    assert pool.drain(timeout=180)
    jobs = {j["case_id"]: j for j in queue.finished()}
    assert sorted(jobs) == sorted(ids) and all(j["state"] == "done" for j in jobs.values())
    assert jobs[held[0]["case_id"]]["attempts"] == 2      # claimed again after the crash
    assert all(CaseStore(home).get(cid)["status"] == "done" for cid in ids)


def test_a_job_that_kills_its_worker_every_time_fails_and_says_so(home, monkeypatch):
    queue_up(home)
    queue = JobQueue(home)
    cid = queue.queued_ids()[0]
    for _ in range(3):                          # three workers died with it
        job = queue.claim("w:1:0", case_id=cid)
        main.begin_job(job)
        main.release_job(job, "w:1:0")
    assert queue.get(cid)["state"] == "failed"
    case = CaseStore(home).get(cid)
    assert case["status"] == "failed" and case["error"] == main.GAVE_UP
    assert cid not in queue.queued_ids() and main._ACTIVE == set()


def test_with_a_pool_configured_the_server_queues_and_the_pool_traces(recorded, home,
                                                                    monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "WORKERS", 2)
    client = TestClient(main.app)               # (no start-up event: the pool is not up yet)
    address = SPECS["tron-coindcx"]["address"]
    r = client.post("/api/cases", json={"address": address})
    cid = r.json()["id"]
    assert r.status_code == 202 and main._queue().queued_ids() == [cid]   # queued, not run here
    assert client.get(f"/api/cases/{cid}").json()["status"] == "queued"
    again = client.post("/api/cases", json={"address": address})
    assert again.json()["id"] == cid and main._queue().counts()["queued"] == 1

    batch = client.post("/api/cases/batch", json={"rows": [
        {"address": SPECS[w]["address"]} for w in ("eth-bitget", "tron-ofac", "tron-coindcx")]})
    assert batch.json()["workers"] == 2 and batch.json()["progress"]["queued"] == 3

    pool = main.start_pool(2)
    assert pool.drain(timeout=180)
    done = client.get(f"/api/cases/{cid}").json()
    assert (done["status"], done["top_vasp"], done["progress"]) == ("done", "CoinDCX", None)
    table = client.get(f"/api/batches/{batch.json()['id']}").json()
    assert table["progress"]["done"] == 3 and table["progress"]["finished"]
    assert [row["top_vasp"] for row in table["rows"]] == ["Bitget", None, "CoinDCX"]
