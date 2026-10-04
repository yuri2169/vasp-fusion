"""The audit log: who looked up what, and when (`data/audit.duckdb`, or
VASPFUSION_AUDIT_DB).

Append-only and hash-chained: each row's hash is an HMAC-SHA256, under the audit key,
of its own fields and the hash of the row before it. A row that is edited, removed or
moved breaks every hash after it, and `verify_chain` names the first broken row. The
recipe is public but the key is not, so the log cannot be rewritten and rehashed by
someone who has the database file and not the key.

The key: VASPFUSION_AUDIT_KEY (32 characters or more; best, because it can be kept off
this machine's disk), or else 32 random bytes written once to `<log file>.key` (mode
0600) beside the log.

What this does not show:
* whoever holds BOTH the log and the key can rewrite it. With the key in a file beside
  the log, that is anyone with write access to the data folder;
* rows cut off the END of the log leave a valid, shorter chain.
`head()` gives the last row's number and hash. Noted somewhere else (a register, a mail
to a supervisor), it pins everything up to that row against both.

A row never holds a request body: only who, what action, on which case, wallet,
exchange or request, and the HTTP status that came back.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .connect import connect

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


def row_hash(row: dict, key: bytes = b"") -> str:
    """HMAC-SHA256 of the row under `key`. With no key it is a plain SHA-256, which is
    what a forger without the key can compute (and what the mock fixture uses)."""
    body = json.dumps([row[k] for k in FIELDS], separators=(",", ":"), ensure_ascii=True)
    if key:
        return hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
    return hashlib.sha256(body.encode()).hexdigest()


def load_key(log_path: Path) -> bytes:
    env = os.environ.get("VASPFUSION_AUDIT_KEY", "")
    if env:
        if len(env) < 32:
            raise ValueError("VASPFUSION_AUDIT_KEY must be at least 32 characters")
        return env.encode()
    path = log_path.with_name(log_path.name + ".key")
    if not path.exists():
        try:                                  # O_EXCL: two processes cannot both write one
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as f:
                f.write(secrets.token_hex(32))
    key = path.read_text().strip()
    if len(key) < 32:
        raise ValueError(f"{path} does not hold an audit key (32 characters or more)")
    return key.encode()


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{t.microsecond // 1000:03d}Z"


class AuditLog:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or os.environ.get("VASPFUSION_AUDIT_DB") or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.key = load_key(self.path)
        with _WRITE, self._con() as con:
            con.execute(_DDL)

    def _con(self, wait_s: float = 30.0):
        return connect(self.path, wait_s=wait_s)

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
            row["hash"] = row_hash(row, self.key)
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
            elif not hmac.compare_digest(row_hash(row, self.key), row["hash"]):
                why = ("its contents were changed, or the audit key is not the one it was "
                       "written with")
            if why:
                return {"ok": False, "rows": len(rows), "broken_at": row["seq"],
                        "reason": f"Row {row['seq']}: {why}.", "head": self.head()}
            prev, expect = row["hash"], expect + 1
        return {"ok": True, "rows": len(rows), "broken_at": None,
                "reason": None, "head": self.head()}
