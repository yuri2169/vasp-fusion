"""The durable trace queue: nothing queued is lost, and nothing is claimed twice."""
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from vaspfusion.store import queue as Q
from vaspfusion.store.queue import JobQueue

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self, at: float = 1_000.0):
        self.at = at

    def __call__(self) -> float:
        return self.at


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def queue(tmp_path, clock):
    return JobQueue(tmp_path / "case.duckdb", clock=clock)


def test_a_job_is_claimed_once_in_the_order_it_was_queued(queue):
    assert queue.enqueue("c-1", {"max_hops": 3}) and queue.enqueue("c-2")
    first = queue.claim("w:1:0")
    assert (first["case_id"], first["state"], first["params"]) == ("c-1", "running",
                                                                 {"max_hops": 3})
    assert queue.claim("w:2:0")["case_id"] == "c-2"
    assert queue.claim("w:3:0") is None
    assert queue.counts() == {"queued": 0, "running": 2, "done": 0, "failed": 0}


def test_a_case_already_queued_or_running_is_not_queued_again(queue):
    assert queue.enqueue("c-1")
    assert not queue.enqueue("c-1")
    queue.claim("w:1:0")
    assert not queue.enqueue("c-1") and queue.active("c-1")
    assert queue.finish("c-1", "w:1:0", stats={"transfers_read": 7})
    assert not queue.active("c-1")
    assert queue.enqueue("c-1")                     # a finished case can be traced again
    assert queue.get("c-1")["attempts"] == 0


def test_a_named_job_is_claimed_only_while_it_is_still_queued(queue):
    queue.enqueue("c-1"), queue.enqueue("c-2")
    assert queue.claim("w:1:0", case_id="c-2")["case_id"] == "c-2"
    assert queue.claim("w:2:0", case_id="c-2") is None
    assert queue.claim("w:2:0", case_id="nope") is None


def test_queued_work_survives_a_restart(tmp_path):
    JobQueue(tmp_path / "case.duckdb").enqueue("c-1", {"max_hops": 2})
    again = JobQueue(tmp_path / "case.duckdb")       # a new process would do exactly this
    assert again.queued_ids() == ["c-1"]
    assert again.claim("w:1:0")["params"] == {"max_hops": 2}


def test_eight_threads_never_claim_the_same_job(queue):
    for i in range(60):
        queue.enqueue(f"c-{i}")
    got: list[list[str]] = [[] for _ in range(8)]

    def work(n: int):
        while (job := queue.claim(f"w:{n}:0")) is not None:
            got[n].append(job["case_id"])

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    claimed = [c for mine in got for c in mine]
    assert len(claimed) == 60 and len(set(claimed)) == 60


_CLAIMER = """
import json, sys
from vaspfusion.store.queue import JobQueue, worker_name
queue, mine = JobQueue(sys.argv[1]), []
while (job := queue.claim(worker_name())) is not None:
    mine.append(job["case_id"])
print(json.dumps(mine))
"""


def test_three_processes_never_claim_the_same_job(tmp_path):
    queue = JobQueue(tmp_path / "case.duckdb")
    for i in range(45):
        queue.enqueue(f"c-{i}")
    procs = [subprocess.Popen([sys.executable, "-c", _CLAIMER, str(queue.path)], cwd=ROOT,
                              stdout=subprocess.PIPE, text=True) for _ in range(3)]
    got = [json.loads(p.communicate(timeout=120)[0]) for p in procs]
    assert all(p.returncode == 0 for p in procs)
    claimed = [c for mine in got for c in mine]
    assert len(claimed) == 45 and len(set(claimed)) == 45


def test_a_job_whose_worker_went_silent_is_queued_again(queue, clock):
    queue.enqueue("c-1")
    queue.claim("elsewhere:1:0")
    clock.at += queue.lease_s - 1
    assert queue.requeue_stale() == ([], []) and queue.active("c-1")
    queue.beat("c-1", "elsewhere:1:0")              # still alive: the lease starts again
    clock.at += queue.lease_s - 1
    assert queue.requeue_stale() == ([], [])
    clock.at += 2
    assert not queue.active("c-1")
    assert queue.requeue_stale() == (["c-1"], [])
    assert queue.claim("w:2:0")["attempts"] == 2


def test_a_job_whose_process_is_gone_is_queued_again_at_once(queue):
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    queue.enqueue("c-1")
    queue.claim(f"{Q.platform.node() or 'host'}:{gone.pid}:0")
    assert not queue.active("c-1")
    assert queue.enqueue("c-1")                     # the officer asked again: it is replaced
    queue.claim(f"{Q.platform.node() or 'host'}:{gone.pid}:0")
    assert queue.requeue_stale() == (["c-1"], [])


def test_a_live_worker_on_this_machine_keeps_its_job(queue):
    queue.enqueue("c-1")
    queue.claim(Q.worker_name())
    assert queue.requeue_stale() == ([], []) and queue.active("c-1")


def test_a_job_that_keeps_killing_its_worker_fails_after_three_claims(queue, clock):
    queue.enqueue("c-1")
    for attempt in range(1, Q.MAX_ATTEMPTS + 1):
        assert queue.claim("elsewhere:1:0")["attempts"] == attempt
        clock.at += queue.lease_s + 1
        again, failed = queue.requeue_stale()
    assert (again, failed) == ([], ["c-1"])
    job = queue.get("c-1")
    assert job["state"] == "failed" and "3 times" in job["error"]
    assert queue.claim("w:2:0") is None


def test_a_worker_cannot_close_a_job_that_was_taken_from_it(queue, clock):
    queue.enqueue("c-1")
    queue.claim("elsewhere:1:0")
    clock.at += queue.lease_s + 1
    queue.requeue_stale()
    queue.claim("w:2:0")
    assert not queue.beat("c-1", "elsewhere:1:0")
    assert not queue.finish("c-1", "elsewhere:1:0")
    assert queue.get("c-1")["state"] == "running"
    assert queue.finish("c-1", "w:2:0", "failed", error="ProviderError: no")
    assert queue.get("c-1")["error"] == "ProviderError: no"
    with pytest.raises(ValueError):
        queue.finish("c-1", "w:2:0", "queued")


def test_progress_is_kept_while_running_and_dropped_at_the_end(queue):
    queue.enqueue("c-1")
    queue.claim("w:1:0")
    queue.beat("c-1", "w:1:0", {"phase": "outbound", "wallets_read": 3})
    assert queue.get("c-1")["progress"] == {"phase": "outbound", "wallets_read": 3}
    queue.finish("c-1", "w:1:0", stats={"seconds": 0.4})
    done = queue.finished()
    assert done[0]["progress"] is None and done[0]["stats"] == {"seconds": 0.4}


def test_the_heartbeat_thread_keeps_a_long_job(queue, clock):
    queue.enqueue("c-1")
    queue.claim("elsewhere:1:0")
    with queue.working("c-1", "elsewhere:1:0", beat_s=0.01):
        clock.at += queue.lease_s + 5
        import time
        time.sleep(0.2)
        assert queue.active("c-1")
