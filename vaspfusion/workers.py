"""Worker processes: each claims jobs from the trace queue and traces them.

A worker is this same program started as `python -m vaspfusion.cli worker`. It opens the
stores the server uses (their paths come from the environment), shares the response
cache file and the rate limiter with every other worker, and runs a case exactly as the
server would (`api.main.work_one`), so a case is the same whoever traced it.

Processes, not threads: replaying a trace from the cache is Python work that threads of
one interpreter would do one at a time.

A worker that dies leaves its job marked running under its process id; the next idle
worker (or the server, when it starts) sees the process is gone and queues the job again
(`store/queue.py`). `WorkerPool` starts the workers, restarts one that exits, and stops
them all with the server.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from .store.queue import worker_name

ROOT = Path(__file__).resolve().parents[1]
IDLE_S = 0.2            # how long an idle worker waits before it looks at the queue again
RECOVER_S = 5.0         # how often an idle worker looks for jobs a dead worker left behind


def run_worker(n: int = 0, drain: bool = False, idle_s: float = IDLE_S) -> int:
    """Claim and trace until told to stop (SIGTERM / Ctrl-C). With `drain`, stop when
    nothing is queued or running any more. Returns how many cases this worker traced."""
    from .api import main as api
    if os.environ.get("VASPFUSION_LABEL_DB"):
        api.LABEL_DB = Path(os.environ["VASPFUSION_LABEL_DB"])
    api.SHARE_PROGRESS = True
    api.WORKERS = 0                     # a worker never starts workers of its own
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, lambda *_: stop.set())
        except ValueError:              # not the main thread (tests run it in one)
            pass
    worker, done, looked = worker_name(n), 0, 0.0
    while not stop.is_set():
        if api.work_one(worker=worker):
            done += 1
            continue
        if time.monotonic() - looked >= RECOVER_S or drain:
            looked = time.monotonic()
            api.recover()
        if drain:
            counts = api._queue().counts()
            if not counts["queued"] and not counts["running"]:
                break
        stop.wait(idle_s)
    return done


class WorkerPool:
    """`n` worker processes, kept alive until `stop()`."""

    def __init__(self, n: int, env: dict | None = None, drain: bool = False):
        self.n, self.env, self.drain = n, dict(env or os.environ), drain
        self.procs: list[subprocess.Popen | None] = [None] * n
        self._stop = threading.Event()
        self._watch: threading.Thread | None = None

    def _spawn(self, i: int) -> subprocess.Popen:
        cmd = [sys.executable, "-m", "vaspfusion.cli", "worker", "--n", str(i)]
        if self.drain:
            cmd.append("--drain")
        return subprocess.Popen(cmd, cwd=ROOT, env=self.env)

    def start(self) -> "WorkerPool":
        for i in range(self.n):
            self.procs[i] = self._spawn(i)
        if not self.drain:              # a draining pool ends by itself; nothing to restart
            self._watch = threading.Thread(target=self._keep_alive, daemon=True)
            self._watch.start()
        return self

    def _keep_alive(self) -> None:
        while not self._stop.wait(2.0):
            for i, proc in enumerate(self.procs):
                if proc is not None and proc.poll() is not None and not self._stop.is_set():
                    self.procs[i] = self._spawn(i)

    def alive(self) -> int:
        return sum(1 for p in self.procs if p is not None and p.poll() is None)

    def wait(self, timeout: float | None = None) -> list[int | None]:
        """Wait for a draining pool's workers to finish; their exit codes."""
        deadline = None if timeout is None else time.monotonic() + timeout
        codes = []
        for proc in self.procs:
            left = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                codes.append(proc.wait(left) if proc is not None else None)
            except subprocess.TimeoutExpired:
                codes.append(None)
        return codes

    def stop(self, grace_s: float = 5.0) -> None:
        self._stop.set()
        for proc in self.procs:
            if proc is not None and proc.poll() is None:
                proc.terminate()
        deadline = time.monotonic() + grace_s
        for proc in self.procs:
            if proc is None:
                continue
            try:
                proc.wait(max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.kill()
