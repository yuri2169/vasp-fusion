"""Complaints received through the SAHYOG intake API, in the desk database
(`data/desk.duckdb`, or VASPFUSION_DESK_DB), beside the requests that go the other way.

A complaint is stored as one JSON document: what the portal sent, and for each wallet
the case that was opened for it and when its result was handed back. The cases
themselves live in the case store; this is only the link between the two.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

from .connect import connect
from .requests import DEFAULT_DB

_WRITE = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS complaints (
    ref         VARCHAR PRIMARY KEY,
    received_at TIMESTAMP NOT NULL,
    detail      VARCHAR NOT NULL
);
"""


class ComplaintStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or os.environ.get("VASPFUSION_DESK_DB") or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE, connect(self.path) as con:
            con.execute(_DDL)

    def save(self, complaint: dict) -> None:
        at = datetime.fromisoformat(str(complaint["received_at"]).replace("Z", "+00:00"))
        with _WRITE, connect(self.path) as con:
            con.execute("BEGIN")
            con.execute("DELETE FROM complaints WHERE ref = ?", [complaint["complaint_ref"]])
            con.execute("INSERT INTO complaints VALUES (?, ?, ?)",
                        [complaint["complaint_ref"], at.replace(tzinfo=None),
                         json.dumps(complaint, sort_keys=True)])
            con.execute("COMMIT")

    def get(self, ref: str) -> dict | None:
        with connect(self.path) as con:
            row = con.execute("SELECT detail FROM complaints WHERE ref = ?", [ref]).fetchone()
        return json.loads(row[0]) if row else None

    def list(self) -> list[dict]:
        """Whole complaints, newest first."""
        with connect(self.path) as con:
            rows = con.execute("SELECT detail FROM complaints "
                               "ORDER BY received_at DESC, ref DESC").fetchall()
        return [json.loads(r[0]) for r in rows]

    def refs_by_case(self) -> dict[str, str]:
        """case id -> the reference of the (earliest) complaint that reported its wallet."""
        out: dict[str, str] = {}
        for c in reversed(self.list()):
            for w in c["wallets"]:
                if w.get("case_id"):
                    out.setdefault(w["case_id"], c["complaint_ref"])
        return out
