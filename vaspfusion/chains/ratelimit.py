"""One rate limit per provider, shared by every worker.

Free API keys are limited per key, not per process, so the pacing has to be shared too:
a fetcher that only knew its own last call would let eight workers send eight times the
allowed rate and collect refusals. The next free slot of each host is therefore kept in
a small DuckDB file (`data/rate_limit.duckdb`, or VASPFUSION_RATE_DB). A caller books
the next slot in one transaction and then sleeps until it; whoever comes next, from any
thread or process, books the one after. A refusal (HTTP 429) moves the host's next slot
back for everybody, not only for the worker that received it.

Times are wall-clock seconds, because they are compared between processes. Nothing
here opens a socket, and a replay from the cache never calls it.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable

import duckdb

from ..store.connect import connect
from .http import ROOT

DEFAULT_DB = ROOT / "data" / "rate_limit.duckdb"
_DDL = "CREATE TABLE IF NOT EXISTS rate_slots (host VARCHAR NOT NULL, next_at DOUBLE NOT NULL)"
_LOCK = threading.Lock()        # this process's callers queue here, the others on the file


class RateLimiter:
    def __init__(self, path: Path | str | None = None,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep):
        self.path = Path(path or os.environ.get("VASPFUSION_RATE_DB") or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock, self.sleep = clock, sleep
        self._tx(lambda con: con.execute(_DDL))

    def _tx(self, fn):
        with _LOCK:
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
                    time.sleep(0.02 * (attempt + 1))

    def _book(self, host: str, gap: float, not_before: float = 0.0) -> float:
        """Book a slot: returns its time and leaves the one after it `gap` later."""
        def fn(con):
            row = con.execute("SELECT next_at FROM rate_slots WHERE host = ?", [host]).fetchone()
            at = max(self.clock(), not_before, row[0] if row else 0.0)
            con.execute("DELETE FROM rate_slots WHERE host = ?", [host])
            con.execute("INSERT INTO rate_slots VALUES (?, ?)", [host, at + gap])
            return at
        return self._tx(fn)

    def acquire(self, host: str, gap: float) -> float:
        """Wait for the host's next free slot, `gap` seconds after the one before it,
        whoever took that one. Returns the seconds waited."""
        if gap <= 0:
            return 0.0
        wait = self._book(host, gap) - self.clock()
        if wait > 0:
            self.sleep(wait)
        return max(wait, 0.0)

    def penalise(self, host: str, seconds: float) -> None:
        """The host refused a call: nobody sends it another for `seconds`."""
        if seconds > 0:
            self._book(host, 0.0, not_before=self.clock() + seconds)

    def next_at(self, host: str) -> float | None:
        with connect(self.path) as con:
            row = con.execute("SELECT next_at FROM rate_slots WHERE host = ?", [host]).fetchone()
        return row[0] if row else None
