"""The reference portal's own store: one SQLite file, nothing shared with the tool."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

_DDL = """
CREATE TABLE IF NOT EXISTS complaints (ref TEXT PRIMARY KEY, filed_at REAL, detail TEXT);
CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, received_at REAL, digest TEXT,
                                     detail TEXT, letter BLOB);
CREATE TABLE IF NOT EXISTS results (key TEXT PRIMARY KEY, received_at REAL, detail TEXT);
CREATE TABLE IF NOT EXISTS nonces (nonce TEXT PRIMARY KEY, seen_at REAL);
"""
_LOCK = threading.Lock()


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as con:
            con.executescript(_DDL)

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    # ---- nonces: a signed call is good once
    def claim_nonce(self, nonce: str, keep_s: int = 900) -> bool:
        now = time.time()
        with _LOCK, self._con() as con:
            con.execute("DELETE FROM nonces WHERE seen_at < ?", (now - keep_s,))
            try:
                con.execute("INSERT INTO nonces VALUES (?, ?)", (nonce, now))
            except sqlite3.IntegrityError:
                return False
        return True

    # ---- complaints this portal filed with the tool
    def save_complaint(self, ref: str, detail: dict) -> None:
        with _LOCK, self._con() as con:
            row = con.execute("SELECT filed_at FROM complaints WHERE ref = ?", (ref,)).fetchone()
            con.execute("INSERT OR REPLACE INTO complaints VALUES (?, ?, ?)",
                        (ref, row["filed_at"] if row else time.time(), json.dumps(detail)))

    def complaints(self) -> list[dict]:
        with self._con() as con:
            rows = con.execute("SELECT detail FROM complaints ORDER BY filed_at DESC, ref DESC")
            return [json.loads(r["detail"]) for r in rows]

    # ---- requests received from the tool
    def request(self, rid: str) -> dict | None:
        with self._con() as con:
            row = con.execute("SELECT * FROM requests WHERE id = ?", (rid,)).fetchone()
        return {"digest": row["digest"], "received_at": row["received_at"],
                **json.loads(row["detail"])} if row else None

    def add_request(self, rid: str, digest: str, detail: dict, letter: bytes) -> None:
        with _LOCK, self._con() as con:
            con.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
                        (rid, time.time(), digest, json.dumps(detail), letter))

    def update_request(self, rid: str, detail: dict) -> None:
        with _LOCK, self._con() as con:
            con.execute("UPDATE requests SET detail = ? WHERE id = ?", (json.dumps(detail), rid))

    def requests(self) -> list[dict]:
        with self._con() as con:
            rows = con.execute("SELECT detail FROM requests ORDER BY received_at DESC, id DESC")
            return [json.loads(r["detail"]) for r in rows]

    def letter(self, rid: str) -> bytes | None:
        with self._con() as con:
            row = con.execute("SELECT letter FROM requests WHERE id = ?", (rid,)).fetchone()
        return bytes(row["letter"]) if row else None

    # ---- results received from the tool, one per wallet of a complaint
    def save_result(self, key: str, detail: dict) -> None:
        with _LOCK, self._con() as con:
            con.execute("INSERT OR REPLACE INTO results VALUES (?, ?, ?)",
                        (key, time.time(), json.dumps(detail)))

    def results(self) -> dict[str, dict]:
        with self._con() as con:
            return {r["key"]: json.loads(r["detail"])
                    for r in con.execute("SELECT key, detail FROM results")}
