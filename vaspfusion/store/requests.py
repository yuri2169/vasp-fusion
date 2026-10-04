"""Requests to exchanges in DuckDB (`data/desk.duckdb`, or VASPFUSION_DESK_DB).

A request is stored as the RequestDetail JSON the API returns, with the columns we
filter and sort on beside it. It is a snapshot: the letter and the payload are fixed
when the request is drafted and do not change when a case is traced again.

A connection is opened per call, as in store/cases.py, so the API server and the CLI
can share the file.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import duckdb

from .connect import connect

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "desk.duckdb"

_WRITE = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS requests (
    id         VARCHAR PRIMARY KEY,
    vasp       VARCHAR NOT NULL,
    status     VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    detail     VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS request_numbers (
    year INTEGER PRIMARY KEY,
    last INTEGER NOT NULL
);
"""


class RequestStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or os.environ.get("VASPFUSION_DESK_DB") or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE, self._con() as con:
            con.execute(_DDL)

    def _con(self, wait_s: float = 30.0):
        return connect(self.path, wait_s=wait_s)

    # ------------------------------------------------------------------ writes
    def next_id(self, year: int) -> tuple[str, str]:
        """The next request id and reference of a year. A number is spent when it is
        handed out, so a draft that fails to save never shares one with a later request."""
        with _WRITE, self._con() as con:
            con.execute("BEGIN")
            row = con.execute("SELECT last FROM request_numbers WHERE year = ?",
                              [year]).fetchone()
            n = (row[0] if row else 0) + 1
            con.execute("DELETE FROM request_numbers WHERE year = ?", [year])
            con.execute("INSERT INTO request_numbers VALUES (?, ?)", [year, n])
            con.execute("COMMIT")
        return f"req-{year}-{n:04d}", f"VF/REQ/{year}/{n:04d}"

    def save(self, request: dict) -> None:
        created = datetime.fromisoformat(str(request["created_at"]).replace("Z", "+00:00"))
        row = [request["id"], request["vasp"], request["status"], created.replace(tzinfo=None),
               json.dumps(request, sort_keys=True)]
        with _WRITE:
            for attempt in range(5):
                try:
                    with self._con() as con:
                        con.execute("BEGIN")
                        con.execute("DELETE FROM requests WHERE id = ?", [request["id"]])
                        con.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?)", row)
                        con.execute("COMMIT")
                    return
                except duckdb.TransactionException:
                    if attempt == 4:
                        raise
                    time.sleep(0.05 * (attempt + 1))

    # ------------------------------------------------------------------ reads
    def get(self, request_id: str) -> dict | None:
        with self._con() as con:
            row = con.execute("SELECT detail FROM requests WHERE id = ?",
                              [request_id]).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, vasp: str | None = None) -> list[dict]:
        """Whole requests, newest first."""
        clause, params = ("WHERE vasp = ?", [vasp]) if vasp else ("", [])
        with self._con() as con:
            rows = con.execute(f"SELECT detail FROM requests {clause} "
                               "ORDER BY created_at DESC, id DESC", params).fetchall()
        return [json.loads(r[0]) for r in rows]
