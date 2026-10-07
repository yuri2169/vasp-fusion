"""Cases in DuckDB (`data/case.duckdb`, or VASPFUSION_CASE_DB).

A case is stored as the CaseDetail JSON the API returns, with the columns we
filter and sort on beside it. `case_wallets` lists every address in a case's
graph, so a wallet page can say which cases it appears in.

A connection is opened per call (as chains/cache.py does), so the API server and
the CLI can share the file: the second writer waits for the lock.
"""
from __future__ import annotations

import json
import logging
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

log = logging.getLogger(__name__)

# What a case has gained since the first cases were stored, and what a case stored before
# then is given when it is read: the value a trace of that time would have had. A null is
# read like an absent field. (The risk block is worked out on every read and never stored.)
ADDED_SINCE = {
    "screening": lambda d: None,                    # not screened: said as such
    "threats": lambda d: [],
    "chains": lambda d: [d["chain"]] if d.get("status") == "done" else [],
    "crossings": lambda d: [],
    "tx_chains": lambda d: {},
    "trace_summary": lambda d: None,                # not counted then
}
# Without these a record is not a case at all.
_PARTS = ("id", "address", "chain", "status", "created_at", "hop_rail", "graph", "candidates",
          "typology_flags", "narrative", "provenance")
_ROW = "id, address, chain, status, created_at, detail"


def _unreadable(row, why: str) -> dict:
    """A stored record that cannot be read, as a failed case that says so: built from the
    columns beside it, so it is still listed under its id and can be traced again."""
    from ..cases import skeleton
    cid, address, chain, _, created, _ = row
    log.warning("stored case %s cannot be read: %s", cid, why)
    return skeleton({
        "id": cid, "address": address, "chain": chain, "status": "failed", "outcome": None,
        "created_at": created.isoformat() + "Z",
        "error": f"The stored record of case {cid} cannot be read ({why}). "
                 "Trace the wallet again to replace it."})


def _load(row, as_stored: bool = False) -> dict:
    """One row of `cases` (`_ROW`) as a case of today's shape."""
    try:
        detail = json.loads(row[5])
    except ValueError:
        return _unreadable(row, "it is not valid JSON")
    if not isinstance(detail, dict):
        return _unreadable(row, "it is not a case")
    missing = [k for k in _PARTS if detail.get(k) is None]
    if missing:
        return _unreadable(row, "it has no " + ", ".join(missing))
    if not as_stored:
        for field, default in ADDED_SINCE.items():
            if detail.get(field) is None:
                detail[field] = default(detail)
    return detail


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
        detail = self.get(case_id, as_stored=True)    # written back as it was stored
        if detail is None:
            raise KeyError(case_id)
        self.save({**detail, "status": status, "error": error})

    # ------------------------------------------------------------------ reads
    def get(self, case_id: str, as_stored: bool = False) -> dict | None:
        """The case, with the fields added since it was stored filled in (`ADDED_SINCE`).
        `as_stored` leaves them out: a content digest is checked against the record as it
        was written."""
        with self._con() as con:
            row = con.execute(f"SELECT {_ROW} FROM cases WHERE id = ?", [case_id]).fetchone()
        return _load(row, as_stored) if row else None

    def unreadable(self, case_id: str, why: str) -> dict | None:
        """The case as a failed one that says its record cannot be read: for a reader that
        found it does not fit the contract."""
        with self._con() as con:
            row = con.execute(f"SELECT {_ROW} FROM cases WHERE id = ?", [case_id]).fetchone()
        return _unreadable(row, why) if row else None

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
            rows = con.execute("SELECT c.id, c.address, c.chain, c.status, c.created_at, "
                               "c.detail FROM cases c JOIN wanted w ON w.id = c.id").fetchall()
        return {r[0]: _load(r) for r in rows}

    def find(self, chain: str, address: str) -> dict | None:
        """The newest case opened on this wallet, if any."""
        with self._con() as con:
            row = con.execute(f"SELECT {_ROW} FROM cases WHERE chain = ? AND address = ? "
                              "ORDER BY created_at DESC, id LIMIT 1", [chain, address]).fetchone()
        return _load(row) if row else None

    def list(self, outcome: str | None = None, status: str | None = None) -> list[dict]:
        """Summaries, newest first. A record that cannot be read is listed as well (as
        failed, with why), unless the filter asks for something it cannot be."""
        where, params = [], []
        for col, val in (("outcome", outcome), ("status", status)):
            if val:
                where.append(f"{col} = ?")
                params.append(val)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._con() as con:
            rows = con.execute(f"SELECT {_ROW} FROM cases {clause} "
                               "ORDER BY created_at DESC, id", params).fetchall()
        return [{k: d.get(k) for k in SUMMARY_KEYS} for d in map(_load, rows)
                if (not outcome or d.get("outcome") == outcome)
                and (not status or d["status"] == status)]

    def wallet_cases(self, address: str, chain: str) -> list[dict]:
        with self._con() as con:
            rows = con.execute("SELECT case_id, role, hop FROM case_wallets WHERE address = ? "
                               "AND chain = ? ORDER BY case_id", [address, chain]).fetchall()
        return [{"case_id": r[0], "role": r[1], "hop": r[2]} for r in rows]
