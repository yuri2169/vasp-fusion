"""Watched wallets in DuckDB (`data/watch.duckdb`, or VASPFUSION_WATCH_DB).

One row per wallet, stored as JSON with its baseline snapshot (vaspfusion/watch.py).
A connection is opened per call, as in store/cases.py.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import duckdb

from .connect import connect

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "watch.duckdb"

_WRITE = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS watch (
    id       VARCHAR PRIMARY KEY,
    chain    VARCHAR NOT NULL,
    address  VARCHAR NOT NULL,
    added_at VARCHAR NOT NULL,
    detail   VARCHAR NOT NULL
);
"""


def watch_id(chain: str, address: str) -> str:
    return f"{chain}-{address}"


class WatchStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or os.environ.get("VASPFUSION_WATCH_DB") or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE, self._con() as con:
            con.execute(_DDL)

    def _con(self, wait_s: float = 30.0):
        return connect(self.path, wait_s=wait_s)

    def save(self, entry: dict) -> None:
        row = [entry["id"], entry["chain"], entry["address"], entry["added_at"],
               json.dumps(entry, sort_keys=True)]
        with _WRITE, self._con() as con:
            con.execute("BEGIN")
            con.execute("DELETE FROM watch WHERE id = ?", [entry["id"]])
            con.execute("INSERT INTO watch VALUES (?, ?, ?, ?, ?)", row)
            con.execute("COMMIT")

    def remove(self, watch_id: str) -> bool:
        with _WRITE, self._con() as con:
            n = con.execute("SELECT count(*) FROM watch WHERE id = ?", [watch_id]).fetchone()[0]
            con.execute("DELETE FROM watch WHERE id = ?", [watch_id])
        return bool(n)

    def get(self, watch_id: str) -> dict | None:
        with self._con() as con:
            row = con.execute("SELECT detail FROM watch WHERE id = ?", [watch_id]).fetchone()
        return json.loads(row[0]) if row else None

    def list(self) -> list[dict]:
        """Every watched wallet, newest first."""
        with self._con() as con:
            rows = con.execute("SELECT detail FROM watch ORDER BY added_at DESC, id").fetchall()
        return [json.loads(r[0]) for r in rows]
