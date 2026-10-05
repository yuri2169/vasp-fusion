"""Open a DuckDB file that other threads and other processes also open.

Every store opens a connection per call, so the API server and the CLI can share a file.
Two things can make `duckdb.connect()` fail for a moment, and both pass by themselves:

* another PROCESS holds the file's write lock (`IOException ... lock`);
* another THREAD of this process is closing its connection to the same file at this
  instant (`BinderException: Unique file handle conflict ... already attached`);
* another THREAD of this process holds the file open the other way (read-only beside
  read-write: `ConnectionException ... different configuration`).

The second one was not waited for until U5: a read beside a write then failed, and the
API answered 500 (`GET /api/cases/{id}` during a refresh, about once in 12).
"""
from __future__ import annotations

import time
from pathlib import Path

import duckdb


def _passing(e: Exception) -> bool:
    text = str(e).lower()
    if isinstance(e, duckdb.IOException):
        return "lock" in text
    return "file handle conflict" in text or "already attached" in text \
        or "different configuration" in text


def connect(path: Path | str, read_only: bool = False, wait_s: float = 30.0):
    deadline = time.monotonic() + wait_s
    while True:
        try:
            return duckdb.connect(str(path), read_only=read_only)
        except (duckdb.IOException, duckdb.BinderException, duckdb.ConnectionException) as e:
            if not _passing(e) or time.monotonic() > deadline:
                raise
            time.sleep(0.02)
