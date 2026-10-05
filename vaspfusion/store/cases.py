"""Cases in DuckDB (`data/case.duckdb`, or VASPFUSION_CASE_DB).

A case is stored as the CaseDetail JSON the API returns, with the columns we
filter and sort on beside it. `case_wallets` lists every address in a case's
graph, so a wallet page can say which cases it appears in.

A connection is opened per call (as chains/cache.py does), so the API server and
the CLI can share the file: the second writer waits for the lock.
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
DEFAULT_DB = ROOT / "data" / "case.duckdb"
SUMMARY_KEYS = ("id", "address", "chain", "status", "outcome", "top_vasp", "confidence",
                "case_ref", "complaint_no", "amount_lost_inr", "created_at", "demo", "error",
                "screening", "threats")

# DuckDB aborts one of two transactions that rewrite the same row at once. Writers in
# this process queue on a lock; a writer in another process is retried.
_WRITE = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS cases (
    id         VARCHAR PRIMARY KEY,
    address    VARCHAR NOT NULL,
    chain      VARCHAR NOT NULL,
    status     VARCHAR NOT NULL,
    outcome    VARCHAR,
    created_at TIMESTAMP NOT NULL,
    detail     VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS case_wallets (
    case_id VARCHAR NOT NULL,
    address VARCHAR NOT NULL,
    chain   VARCHAR NOT NULL,
    role    VARCHAR NOT NULL,
    hop     INTEGER NOT NULL
);
"""


class CaseStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or os.environ.get("VASPFUSION_CASE_DB") or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE, self._con() as con:
            con.execute(_DDL)

    def _con(self, wait_s: float = 30.0):
        return connect(self.path, wait_s=wait_s)

    # ------------------------------------------------------------------ writes
    def save(self, detail: dict) -> None:
        """Insert or replace a case (a full CaseDetail, or `cases.skeleton()` of one)."""
        created = datetime.fromisoformat(str(detail["created_at"]).replace("Z", "+00:00"))
        # by plain address and its own chain: a wallet reached over a bridge has the graph
        # id `chain:address`, and is looked up like any wallet of that chain
        wallets = [(detail["id"], n.get("address") or n["id"], n["chain"], n["role"], n["hop"])
                   for n in detail.get("graph", {}).get("nodes", [])]
        row = [detail["id"], detail["address"], detail["chain"], detail["status"],
               detail.get("outcome"), created.replace(tzinfo=None),
               json.dumps(detail, sort_keys=True)]
        with _WRITE:
            for attempt in range(5):
                try:
                    with self._con() as con:
                        con.execute("BEGIN")
                        con.execute("DELETE FROM cases WHERE id = ?", [detail["id"]])
                        con.execute("DELETE FROM case_wallets WHERE case_id = ?", [detail["id"]])
                        con.execute("INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, ?)", row)
                        if wallets:
                            con.executemany("INSERT INTO case_wallets VALUES (?, ?, ?, ?, ?)",
                                            wallets)
                        con.execute("COMMIT")
                    return
                except duckdb.TransactionException:
                    if attempt == 4:
                        raise
                    time.sleep(0.05 * (attempt + 1))

    def set_status(self, case_id: str, status: str, error: str | None = None) -> None:
        detail = self.get(case_id)
        if detail is None:
            raise KeyError(case_id)
        self.save({**detail, "status": status, "error": error})

    # ------------------------------------------------------------------ reads
    def get(self, case_id: str) -> dict | None:
        with self._con() as con:
            row = con.execute("SELECT detail FROM cases WHERE id = ?", [case_id]).fetchone()
        return json.loads(row[0]) if row else None

    def heads(self, case_ids: list[str]) -> dict[str, dict]:
        """id -> {status, outcome, created_at, error} of many cases in one read, without
        parsing any result (a batch of thousands is polled while it runs)."""
        if not case_ids:
            return {}
        with self._con() as con:
            con.execute("CREATE TEMP TABLE wanted (id VARCHAR)")
            con.executemany("INSERT INTO wanted VALUES (?)", [[c] for c in set(case_ids)])
            rows = con.execute(
                "SELECT c.id, c.status, c.outcome, c.created_at, "
                "json_extract_string(c.detail, '$.error') FROM cases c "
                "JOIN wanted w ON w.id = c.id").fetchall()
        return {r[0]: {"status": r[1], "outcome": r[2], "created_at": str(r[3]), "error": r[4]}
                for r in rows}

    def get_many(self, case_ids: list[str]) -> dict[str, dict]:
        """id -> the whole case, for many cases in one read."""
        if not case_ids:
            return {}
        with self._con() as con:
            con.execute("CREATE TEMP TABLE wanted (id VARCHAR)")
            con.executemany("INSERT INTO wanted VALUES (?)", [[c] for c in set(case_ids)])
            rows = con.execute("SELECT c.id, c.detail FROM cases c "
                               "JOIN wanted w ON w.id = c.id").fetchall()
        return {r[0]: json.loads(r[1]) for r in rows}

    def find(self, chain: str, address: str) -> dict | None:
        """The newest case opened on this wallet, if any."""
        with self._con() as con:
            row = con.execute("SELECT detail FROM cases WHERE chain = ? AND address = ? "
                              "ORDER BY created_at DESC, id LIMIT 1", [chain, address]).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, outcome: str | None = None, status: str | None = None) -> list[dict]:
        where, params = [], []
        for col, val in (("outcome", outcome), ("status", status)):
            if val:
                where.append(f"{col} = ?")
                params.append(val)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._con() as con:
            rows = con.execute(f"SELECT detail FROM cases {clause} "
                               "ORDER BY created_at DESC, id", params).fetchall()
        return [{k: d.get(k) for k in SUMMARY_KEYS} for d in (json.loads(r[0]) for r in rows)]

    def wallet_cases(self, address: str, chain: str) -> list[dict]:
        with self._con() as con:
            rows = con.execute("SELECT case_id, role, hop FROM case_wallets WHERE address = ? "
                               "AND chain = ? ORDER BY case_id", [address, chain]).fetchall()
        return [{"case_id": r[0], "role": r[1], "hop": r[2]} for r in rows]
