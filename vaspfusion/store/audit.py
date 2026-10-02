"""The audit log: who looked up what, and when (`data/audit.duckdb`, or
VASPFUSION_AUDIT_DB).

Append-only and hash-chained: each row's SHA-256 covers its own fields and the hash
of the row before it, so a row that is edited, removed or moved breaks every hash
after it and `verify_chain` names the first broken row.

What the chain cannot show by itself: rows cut off the END of the log. `head()` gives
the last row's number and hash; noted somewhere else (a register, a mail to a
supervisor), it pins everything up to that row.

A row never holds a request body: only who, what action, on which case, wallet,
exchange or request, and the HTTP status that came back.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "audit.duckdb"
GENESIS = "0" * 64
FIELDS = ("seq", "at", "officer", "action", "target", "method", "path", "status", "client",
          "detail", "prev_hash")
COLS = ", ".join(f'"{c}"' for c in FIELDS + ("hash",))      # "at" is a keyword in DuckDB
_WRITE = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS audit (
    seq       BIGINT PRIMARY KEY,
    "at"      VARCHAR NOT NULL,
    officer   VARCHAR,
    action    VARCHAR NOT NULL,
    target    VARCHAR,
    method    VARCHAR NOT NULL,
    path      VARCHAR NOT NULL,
    status    INTEGER NOT NULL,
    client    VARCHAR,
    detail    VARCHAR,
    prev_hash VARCHAR NOT NULL,
    hash      VARCHAR NOT NULL
)"""


def row_hash(row: dict) -> str:
    body = json.dumps([row[k] for k in FIELDS], separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(body.encode()).hexdigest()


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{t.microsecond // 1000:03d}Z"


class AuditLog:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or os.environ.get("VASPFUSION_AUDIT_DB") or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE, self._con() as con:
            con.execute(_DDL)

    def _con(self, wait_s: float = 30.0):
        deadline = time.monotonic() + wait_s
        while True:
            try:
                return duckdb.connect(str(self.path))
            except duckdb.IOException as e:
                if "lock" not in str(e).lower() or time.monotonic() > deadline:
                    raise
                time.sleep(0.05)

    # ------------------------------------------------------------------ write
    def append(self, *, action: str, method: str, path: str, status: int,
               officer: str | None = None, target: str | None = None,
               client: str | None = None, detail: dict | None = None,
               at: datetime | None = None) -> dict:
        """Add one row at the end of the chain and return it."""
        row = {"at": _iso(at or datetime.now(timezone.utc)), "officer": officer,
               "action": action, "target": target, "method": method, "path": path[:500],
               "status": int(status), "client": client,
               "detail": json.dumps(detail, sort_keys=True) if detail else None}
        with _WRITE, self._con() as con:
            con.execute("BEGIN")
            last = con.execute("SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            row["seq"] = (last[0] if last else 0) + 1
            row["prev_hash"] = last[1] if last else GENESIS
            row["hash"] = row_hash(row)
            con.execute("INSERT INTO audit VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [row[k] for k in FIELDS] + [row["hash"]])
            con.execute("COMMIT")
        return self._out(row)

    # ------------------------------------------------------------------ read
    @staticmethod
    def _out(row: dict) -> dict:
        return {**row, "detail": json.loads(row["detail"]) if row["detail"] else None}

    def list(self, limit: int = 100, offset: int = 0, officer: str | None = None,
             action: str | None = None, target: str | None = None) -> tuple[int, list[dict]]:
        """(how many rows match, the page of them), newest first. `action` matches a whole
        action ("case.view") or a family ("case"); `target` matches exactly."""
        where, params = [], []
        if officer:
            where.append("officer = ?")
            params.append(officer)
        if action:
            where.append("(action = ? OR action LIKE ?)")
            params += [action, action.replace("%", "") + ".%"]
        if target:
            where.append("target = ?")
            params.append(target)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._con() as con:
            total = con.execute(f"SELECT count(*) FROM audit {clause}", params).fetchone()[0]
            rows = con.execute(f"SELECT {COLS} FROM audit {clause} ORDER BY seq DESC "
                               f"LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
        return total, [self._out(dict(zip(FIELDS + ("hash",), r))) for r in rows]

    def head(self) -> dict:
        """The end of the chain: note it elsewhere to pin every row up to it."""
        with self._con() as con:
            last = con.execute('SELECT seq, hash, "at" FROM audit ORDER BY seq DESC '
                               'LIMIT 1').fetchone()
        return {"seq": last[0], "hash": last[1], "at": last[2]} if last else \
            {"seq": 0, "hash": GENESIS, "at": None}

    def verify_chain(self) -> dict:
        """Recompute every hash. `ok` false names the first row that does not fit."""
        with self._con() as con:
            rows = con.execute(f"SELECT {COLS} FROM audit ORDER BY seq").fetchall()
        prev, expect = GENESIS, 1
        for r in rows:
            row = dict(zip(FIELDS + ("hash",), r))
            why = None
            if row["seq"] != expect:
                why = f"row {expect} is missing"
            elif row["prev_hash"] != prev:
                why = "it does not follow the row before it"
            elif row_hash(row) != row["hash"]:
                why = "its contents were changed"
            if why:
                return {"ok": False, "rows": len(rows), "broken_at": row["seq"],
                        "reason": f"Row {row['seq']}: {why}.", "head": self.head()}
            prev, expect = row["hash"], expect + 1
        return {"ok": True, "rows": len(rows), "broken_at": None,
                "reason": None, "head": self.head()}
