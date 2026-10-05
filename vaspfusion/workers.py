"""The worker pool: several processes trace at once, one process owns the case store.

Replaying or computing a trace is Python work, which threads of one interpreter would do
one at a time, so the workers are processes. What they share:

* the trace queue (`store/queue.py`): the pool claims each job there, so nothing queued
  is lost by a restart and no case is ever handed to two workers;
* the response cache file: a page one worker fetched is a cache hit for every other;
* the rate limiter (`chains/ratelimit.py`): one pace per provider across all of them.

What they do not share is the case store. A DuckDB file has one writing process at a
time, and opening it costs milliseconds; workers that each opened it ten times a case
spent as long queueing for the file as tracing (measured: docs/scaling.md). So the pool
runs in the process that owns the store (the API server): it claims a job, marks the
case running, hands the stored case to a worker, and stores what comes back. A worker
reads the cache and the labels, traces, and returns the finished case. While the pool
has work it keeps one connection to the store open, which makes each of its own reads
and writes cheap; it lets go when the queue is empty, so the command line can use the
store between batches.

If a worker process dies, every job that was in flight is queued again (three tries,
then the case is marked failed) and the processes are started afresh. If the server
itself dies, its jobs are found at the next start by its process id (`api.recover`).
"""
from __future__ import annotations

import multiprocessing
import os
import queue as _queue
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from .store.connect import connect
from .store.queue import BEAT_S, worker_name

IDLE_S = 0.5            # how long an idle pool waits before it looks at the queue again
RECOVER_S = 5.0         # how often an idle pool looks for jobs a dead process left behind
LET_GO_S = 1.0          # idle this long, the pool closes its connection to the store
_PROGRESS = None        # in a worker process: the queue its progress goes to the pool on


# ------------------------------------------------------------------ in a worker process
def _init(label_db: str, progress) -> None:
    """Runs once in each worker process: where the labels are, where progress goes, and
    the model loaded before the first case needs it."""
    global _PROGRESS
    from .api import main as api
    api.LABEL_DB = Path(label_db)
    api.WORKERS = 0                     # a worker never starts workers of its own
    _PROGRESS = progress
    try:
        from .classify import runtime
        from .classify.train import load_model
        for chain in runtime.SCORED_CHAINS:
            load_model(runtime.MODEL_DIR / chain)
    except Exception:  # noqa: BLE001 - no model on disk: cases are traced without it
        pass


def _ready(seconds: float) -> int:
    """Occupies a worker briefly, so that all of them are started and warm at once."""
    time.sleep(seconds)
    return os.getpid()


def trace_job(payload: dict) -> dict:
    """Trace one wallet in this worker process. Returns `{"detail": the case}` or
    `{"error": why}`, each with `stats` (seconds, what was read, peak memory, pid). The
    case store is not touched: the pool stores the result."""
    from .api import main as api
    cid, params, told = payload["case_id"], payload["params"], [0.0]

    def tell(snapshot: dict) -> None:           # a few times a second is plenty to watch
        if _PROGRESS is not None and (time.monotonic() - told[0] >= 0.25
                                      or snapshot.get("phase") == "checking"):
            told[0] = time.monotonic()
            try:
                _PROGRESS.put_nowait((cid, snapshot))
            except Exception:  # noqa: BLE001 - a watcher's view is not the trace's problem
                pass

    stats: dict = {}
    started = time.perf_counter()
    incident, _, budget = api._job_args({"params": params}, None)
    try:
        out = {"detail": api.trace_only(payload["queued"], params.get("max_hops", 3), incident,
                                        budget, tell, stats, payload.get("label_sha"))}
    except Exception as e:  # noqa: BLE001 - whatever went wrong, the case must say so
        out = {"error": f"{type(e).__name__}: {e}"[:500]}
    stats.update(seconds=round(time.perf_counter() - started, 4), peak_mb=api._peak_mb(),
                 pid=os.getpid())
    out["stats"] = stats
    return out


# ------------------------------------------------------------------ in the owning process
class WorkerPool:
    """`n` worker processes behind the queue of the process that creates it."""

    def __init__(self, n: int):
        from .api import main as api
        self.api, self.n = api, n
        self.name = worker_name()
        self._ctx = multiprocessing.get_context("spawn")
        self._progress = self._ctx.Queue()
        self._executor: ProcessPoolExecutor | None = None
        self._inflight: dict[Future, tuple[dict, dict]] = {}
        self._stop, self._wake = threading.Event(), threading.Event()
        self._threads: list[threading.Thread] = []
        self._anchor = None
        self.pids: set[int] = set()

    # -------------------------------------------------------------- life cycle
    def _spawn(self) -> None:
        self._executor = ProcessPoolExecutor(
            max_workers=self.n, mp_context=self._ctx, initializer=_init,
            initargs=(str(self.api.LABEL_DB), self._progress))
        for f in [self._executor.submit(_ready, 0.3) for _ in range(self.n)]:
            f.add_done_callback(lambda done: done.exception() or self.pids.add(done.result()))

    def start(self) -> "WorkerPool":
        self._spawn()
        for target in (self._loop, self._watch_progress):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self._threads.append(thread)
        return self

    def wake(self) -> None:
        """Something was queued: look now instead of at the next idle check."""
        self._wake.set()

    def busy(self) -> bool:
        counts = self.api._queue().counts()
        return bool(self._inflight or counts["queued"] or counts["running"])

    def drain(self, timeout: float = 3600.0) -> bool:
        """Wait until nothing is queued or in flight. False if `timeout` came first."""
        deadline = time.monotonic() + timeout
        self.wake()
        while time.monotonic() < deadline:
            if not self.busy():
                return True
            time.sleep(0.05)
        return False

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        for thread in self._threads:
            thread.join(timeout=10)
        self._kill()
        self._let_go()
        try:
            self._progress.close()
        except Exception:  # noqa: BLE001
            pass

    def _kill(self) -> None:
        if self._executor is None:
            return
        procs = list((getattr(self._executor, "_processes", None) or {}).values())
        self._executor.shutdown(wait=False, cancel_futures=True)
        for proc in procs:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001 - already gone
                pass
        self._executor = None

    def worker_pids(self) -> list[int]:
        return sorted((getattr(self._executor, "_processes", None) or {}))

    # -------------------------------------------------------------- the store connection
    def _hold(self) -> None:
        if self._anchor is None:
            self._anchor = connect(self.api._queue().path)

    def _let_go(self) -> None:
        if self._anchor is not None:
            try:
                self._anchor.close()
            finally:
                self._anchor = None

    # -------------------------------------------------------------- the loop
    def _loop(self) -> None:
        api = self.api
        beat = recovered = idle_since = time.monotonic()
        while not self._stop.is_set():
            moved = False
            try:
                broken = False
                for future in [f for f in self._inflight if f.done()]:
                    job, payload = self._inflight.pop(future)
                    moved = True
                    try:
                        result = future.result()
                    except BrokenProcessPool:
                        broken = True
                        api.release_job(job, self.name)
                        continue
                    except Exception as e:  # noqa: BLE001 - e.g. a result that cannot be sent
                        result = {"error": f"{type(e).__name__}: {e}"[:500], "stats": {}}
                    if result.get("stats", {}).get("pid"):
                        self.pids.add(result["stats"]["pid"])
                    api.end_job(job, payload, result, self.name)
                if broken:                      # a worker died: start the processes afresh
                    for job, _ in self._inflight.values():
                        api.release_job(job, self.name)
                    self._inflight.clear()
                    self._kill()
                    self._spawn()
                while len(self._inflight) < self.n and not self._stop.is_set():
                    job = api._queue().claim(self.name)
                    if job is None:
                        break
                    moved = True
                    self._hold()
                    payload = api.begin_job(job)
                    if payload is None:
                        api._queue().finish(job["case_id"], self.name, "failed",
                                            error="The case is no longer in the store.")
                        continue
                    try:
                        self._inflight[self._executor.submit(trace_job, payload)] = (job, payload)
                    except BrokenProcessPool:
                        api.release_job(job, self.name)
                        self._kill()
                        self._spawn()
                now = time.monotonic()
                if self._inflight and now - beat >= BEAT_S:
                    beat = now
                    for job, _ in self._inflight.values():
                        api._queue().beat(job["case_id"], self.name)
                if not self._inflight and now - recovered >= RECOVER_S:
                    recovered = now
                    api.recover()
            except Exception:  # noqa: BLE001 - the store was busy or away: try again shortly
                time.sleep(0.2)
            if moved or self._inflight:
                idle_since = time.monotonic()
            elif time.monotonic() - idle_since >= LET_GO_S:
                self._let_go()
            if moved:
                continue
            if self._inflight:
                wait(list(self._inflight), timeout=0.05, return_when=FIRST_COMPLETED)
            else:
                self._wake.wait(IDLE_S)
                self._wake.clear()

    def _watch_progress(self) -> None:
        """What the workers say they have read goes where the server keeps progress."""
        while not self._stop.is_set():
            try:
                cid, snapshot = self._progress.get(timeout=0.2)
            except _queue.Empty:
                continue
            except Exception:  # noqa: BLE001 - the queue was closed
                return
            if any(job["case_id"] == cid for job, _ in list(self._inflight.values())):
                self.api._note_progress(cid, snapshot)
