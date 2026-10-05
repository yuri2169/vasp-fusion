"""The trace queue, as a table in the case store (`trace_jobs` in `data/case.duckdb`).

A wallet waiting to be traced is a row here, so a restart loses no queued work, and a
claim is one statement on the one connection that may write the file, so no two workers
(threads of this process, or other processes) ever hold the same job.

A job is `queued`, then `running` under the worker that claimed it, then `done` or
`failed`. A running job whose worker has died (its process is gone, or it stopped
saying it is alive) is queued again; after `MAX_ATTEMPTS` claims it fails instead, so a
wallet that kills its worker every time cannot loop for ever.

Times are wall-clock seconds, because they are compared between processes.
"""
from __future__ import annotations

import json
import os
import platform
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import duckdb

from .cases import _WRITE, DEFAULT_DB
from .connect import connect

LEASE_S = 60.0          # a running job silent for this long is taken to be abandoned
BEAT_S = 10.0           # how often a worker says it is still on a job
MAX_ATTEMPTS = 3
ACTIVE = ("queued", "running")

_DDL = """
CREATE TABLE IF NOT EXISTS trace_jobs (
    case_id      VARCHAR NOT NULL,
    seq          BIGINT NOT NULL,
    state        VARCHAR NOT NULL,
    params       VARCHAR NOT NULL,
    enqueued_at  DOUBLE NOT NULL,
    worker       VARCHAR,
    claimed_at   DOUBLE,
    heartbeat_at DOUBLE,
    finished_at  DOUBLE,
    attempts     INTEGER NOT NULL,
    progress     VARCHAR,
    stats        VARCHAR,
    error        VARCHAR
)"""
_COLS = ("case_id", "seq", "state", "params", "enqueued_at", "worker", "claimed_at",
         "heartbeat_at", "finished_at", "attempts", "progress", "stats", "error")
_JSON = ("params", "progress", "stats")


def worker_name(n: int = 0) -> str:
    """host:pid:n. The host and pid are how a dead worker is told from a slow one."""
    return f"{platform.node() or 'host'}:{os.getpid()}:{n}"


def _process_gone(worker: str | None) -> bool:
    """True only when the worker ran on this machine and its process no longer exists."""
    if not worker or os.name == "nt":       # no harmless "does it exist" signal on Windows
        return False
    host, _, rest = worker.rpartition(":")[0].rpartition(":")
    if host != (platform.node() or "host") or not rest.isdigit():
        return False
    try:
        os.kill(int(rest), 0)
    except ProcessLookupError:
        return True
    except OSError:                          # it exists, under another user
        return False
    return False


def _row(values) -> dict:
    job = dict(zip(_COLS, values))
    for k in _JSON:
        job[k] = json.loads(job[k]) if job[k] else None
    return job


class JobQueue:
    def __init__(self, path: Path | str | None = None,
                 clock: Callable[[], float] = time.time, lease_s: float = LEASE_S):
        self.path = Path(path or os.environ.get("VASPFUSION_CASE_DB") or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock, self.lease_s = clock, lease_s
        self._tx(lambda con: con.execute(_DDL))

    def _tx(self, fn):
        """Run `fn(con)` as one transaction. Writers of this process queue on the store's
        lock; a writer in another process holds the file, and `connect` waits for it."""
        with _WRITE:
            for attempt in range(5):
                try:
                    with connect(self.path) as con:
                        con.execute("BEGIN")
                        out = fn(con)
                        con.execute("COMMIT")
                    return out
                except duckdb.TransactionException:
                    if attempt == 4:
                        raise
                    time.sleep(0.05 * (attempt + 1))

    def _read(self, sql: str, params: list | None = None) -> list:
        with connect(self.path) as con:
            return con.execute(sql, params or []).fetchall()

    def _stale(self, job: dict) -> bool:
        if job["state"] != "running":
            return False
        beat = job["heartbeat_at"] or job["claimed_at"] or 0.0
        return _process_gone(job["worker"]) or self.clock() - beat > self.lease_s

    # ------------------------------------------------------------------ writes
    def enqueue(self, case_id: str, params: dict | None = None) -> bool:
        """Queue the case's trace. False when it is already queued or being traced (a
        job its dead worker left behind does not count: it is replaced)."""
        def fn(con):
            old = con.execute(f"SELECT {', '.join(_COLS)} FROM trace_jobs WHERE case_id = ?",
                              [case_id]).fetchone()
            if old is not None:
                job = _row(old)
                if job["state"] in ACTIVE and not self._stale(job):
                    return False
                con.execute("DELETE FROM trace_jobs WHERE case_id = ?", [case_id])
            seq = con.execute("SELECT coalesce(max(seq), 0) + 1 FROM trace_jobs").fetchone()[0]
            con.execute("INSERT INTO trace_jobs (case_id, seq, state, params, enqueued_at, "
                        "attempts) VALUES (?, ?, 'queued', ?, ?, 0)",
                        [case_id, seq, json.dumps(params or {}, sort_keys=True), self.clock()])
            return True
        return self._tx(fn)

    def claim(self, worker: str, case_id: str | None = None) -> dict | None:
        """Take the oldest queued job (or the named one, if it is still queued) for
        `worker`. None when there is nothing to take."""
        def fn(con):
            pick = "SELECT case_id FROM trace_jobs WHERE state = 'queued'" + \
                   (" AND case_id = ?" if case_id else "") + " ORDER BY seq LIMIT 1"
            found = con.execute(pick, [case_id] if case_id else []).fetchone()
            if found is None:
                return None
            now = self.clock()
            con.execute("UPDATE trace_jobs SET state = 'running', worker = ?, claimed_at = ?, "
                        "heartbeat_at = ?, attempts = attempts + 1, progress = NULL "
                        "WHERE case_id = ? AND state = 'queued'", [worker, now, now, found[0]])
            return _row(con.execute(f"SELECT {', '.join(_COLS)} FROM trace_jobs "
                                    "WHERE case_id = ?", [found[0]]).fetchone())
        return self._tx(fn)

    def beat(self, case_id: str, worker: str, progress: dict | None = None) -> bool:
        """The worker is still on the job (and, optionally, what its trace has read so
        far). False when the job is no longer its own: it was taken to be abandoned."""
        def fn(con):
            sets, params = "heartbeat_at = ?", [self.clock()]
            if progress is not None:
                sets, params = sets + ", progress = ?", params + [json.dumps(progress)]
            got = con.execute(f"UPDATE trace_jobs SET {sets} WHERE case_id = ? AND worker = ? "
                              "AND state = 'running' RETURNING case_id",
                              params + [case_id, worker]).fetchall()
            return bool(got)
        return self._tx(fn)

    def finish(self, case_id: str, worker: str, state: str = "done",
               stats: dict | None = None, error: str | None = None) -> bool:
        """Close the job. False (and nothing changes) when it is no longer the worker's."""
        if state not in ("done", "failed"):
            raise ValueError(f"a job ends done or failed, not {state}")

        def fn(con):
            got = con.execute(
                "UPDATE trace_jobs SET state = ?, finished_at = ?, stats = ?, error = ?, "
                "progress = NULL WHERE case_id = ? AND worker = ? AND state = 'running' "
                "RETURNING case_id",
                [state, self.clock(), json.dumps(stats) if stats else None, error,
                 case_id, worker]).fetchall()
            return bool(got)
        return self._tx(fn)

    def requeue_stale(self) -> tuple[list[str], list[str]]:
        """Queue again every running job whose worker is gone; a job that has already
        been claimed `MAX_ATTEMPTS` times fails instead. Returns (requeued, failed)."""
        def fn(con):
            rows = con.execute(f"SELECT {', '.join(_COLS)} FROM trace_jobs "
                               "WHERE state = 'running'").fetchall()
            again, failed = [], []
            for job in map(_row, rows):
                if not self._stale(job):
                    continue
                if job["attempts"] >= MAX_ATTEMPTS:
                    con.execute("UPDATE trace_jobs SET state = 'failed', finished_at = ?, "
                                "error = ? WHERE case_id = ?",
                                [self.clock(), f"The trace stopped {job['attempts']} times "
                                 "before it finished.", job["case_id"]])
                    failed.append(job["case_id"])
                else:
                    con.execute("UPDATE trace_jobs SET state = 'queued', worker = NULL, "
                                "progress = NULL WHERE case_id = ?", [job["case_id"]])
                    again.append(job["case_id"])
            return again, failed
        return self._tx(fn)

    @contextmanager
    def working(self, case_id: str, worker: str, beat_s: float = BEAT_S):
        """While the block runs, a thread keeps the job's heartbeat fresh."""
        stop = threading.Event()

        def beats():
            while not stop.wait(beat_s):
                try:
                    self.beat(case_id, worker)
                except Exception:  # noqa: BLE001 - a missed beat is not the trace's problem
                    pass

        thread = threading.Thread(target=beats, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join()

    # ------------------------------------------------------------------ reads
    def get(self, case_id: str) -> dict | None:
        rows = self._read(f"SELECT {', '.join(_COLS)} FROM trace_jobs WHERE case_id = ?",
                          [case_id])
        return _row(rows[0]) if rows else None

    def active(self, case_id: str) -> bool:
        """Is the case queued, or being traced by a worker that is alive?"""
        job = self.get(case_id)
        return job is not None and job["state"] in ACTIVE and not self._stale(job)

    def active_ids(self) -> set[str]:
        rows = self._read(f"SELECT {', '.join(_COLS)} FROM trace_jobs "
                          "WHERE state IN ('queued', 'running')")
        return {j["case_id"] for j in map(_row, rows) if not self._stale(j)}

    def queued_ids(self) -> list[str]:
        return [r[0] for r in self._read("SELECT case_id FROM trace_jobs "
                                         "WHERE state = 'queued' ORDER BY seq")]

    def counts(self) -> dict[str, int]:
        found = dict(self._read("SELECT state, count(*) FROM trace_jobs GROUP BY state"))
        return {s: int(found.get(s, 0)) for s in ("queued", "running", "done", "failed")}

    def finished(self) -> list[dict]:
        """Every closed job, oldest first (the bench reads its timings from here)."""
        rows = self._read(f"SELECT {', '.join(_COLS)} FROM trace_jobs "
                          "WHERE state IN ('done', 'failed') ORDER BY finished_at, seq")
        return [_row(r) for r in rows]
