"""Batches of wallets, in the case store (`batches`, `batch_rows` in `data/case.duckdb`).

A batch records what was uploaded: every row as it was given, and for each row either
the case that was opened for it or the reason it was refused. The cases themselves, and
their place in the trace queue, live in their own tables; a batch is only the list.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .cases import _WRITE, DEFAULT_DB
from .connect import connect

_DDL = """
CREATE TABLE IF NOT EXISTS batches (
    id         VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    detail     VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS batch_rows (
    batch_id VARCHAR NOT NULL,
    row_no   INTEGER NOT NULL,
    detail   VARCHAR NOT NULL
);
"""


class BatchStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or os.environ.get("VASPFUSION_CASE_DB") or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE, connect(self.path) as con:
            con.execute(_DDL)

    def save(self, batch: dict, rows: list[dict]) -> None:
        """Insert or replace a batch (its header) and all its rows."""
        at = datetime.fromisoformat(str(batch["created_at"]).replace("Z", "+00:00"))
        with _WRITE, connect(self.path) as con:
            con.execute("BEGIN")
            con.execute("DELETE FROM batches WHERE id = ?", [batch["id"]])
            con.execute("DELETE FROM batch_rows WHERE batch_id = ?", [batch["id"]])
            con.execute("INSERT INTO batches VALUES (?, ?, ?)",
                        [batch["id"], at.replace(tzinfo=None), json.dumps(batch, sort_keys=True)])
            if rows:
                con.executemany("INSERT INTO batch_rows VALUES (?, ?, ?)",
                                [[batch["id"], r["row"], json.dumps(r, sort_keys=True)]
                                 for r in rows])
            con.execute("COMMIT")

    def get(self, batch_id: str) -> tuple[dict, list[dict]] | None:
        with connect(self.path) as con:
            head = con.execute("SELECT detail FROM batches WHERE id = ?", [batch_id]).fetchone()
            if head is None:
                return None
            rows = con.execute("SELECT detail FROM batch_rows WHERE batch_id = ? "
                               "ORDER BY row_no", [batch_id]).fetchall()
        return json.loads(head[0]), [json.loads(r[0]) for r in rows]

    def list(self) -> list[dict]:
        with connect(self.path) as con:
            rows = con.execute("SELECT detail FROM batches ORDER BY created_at DESC, id").fetchall()
        return [json.loads(r[0]) for r in rows]

    def case_ids(self, batch_id: str) -> list[str]:
        found = self.get(batch_id)
        return [r["case_id"] for r in found[1] if r.get("case_id")] if found else []
