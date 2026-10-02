"""Officer accounts: `data/officers.json` (or VASPFUSION_OFFICERS), git-ignored.

A password is stored only as its scrypt hash with a salt of its own. Five wrong
passwords in a row lock the account for five minutes (counted in this process).
Accounts are added from the command line (`cli officer add`), not through the API:
whoever can run the tool on the workstation decides who may sign in.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FILE = ROOT / "data" / "officers.json"
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
MIN_PASSWORD = 10
MAX_FAILS, LOCK_S = 5, 300

_LOCK = threading.Lock()
_FAILS: dict[tuple[str, str], tuple[int, float]] = {}    # (file, user) -> (fails, locked until)


class Locked(Exception):
    """Too many wrong passwords; try again later."""


def _hash(password: str, salt: bytes, params: dict) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=params["n"], r=params["r"],
                          p=params["p"], dklen=32).hex()


def _public(row: dict) -> dict:
    return {"username": row["username"], "name": row["name"], "post": row.get("post")}


class Officers:
    def __init__(self, path: Path | str | None = None, clock: Callable[[], float] = time.time):
        self.path = Path(path or os.environ.get("VASPFUSION_OFFICERS") or DEFAULT_FILE)
        self.clock = clock

    # ------------------------------------------------------------------ file
    def _rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text()).get("officers", [])

    def _write(self, rows: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"officers": rows}, f, indent=1)
            f.write("\n")
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------ manage
    def add(self, username: str, name: str, password: str, post: str | None = None) -> dict:
        if not USERNAME.match(username or ""):
            raise ValueError("A user name is 2 to 32 characters: small letters, digits, "
                             "dot, dash, underscore.")
        name = " ".join((name or "").split())
        if not name:
            raise ValueError("Give the officer's name.")
        try:                              # it is printed on letters in a standard PDF font
            f"{name} {post or ''}".encode("cp1252")
        except UnicodeEncodeError:
            raise ValueError("Write the officer's name and post in Latin letters.") from None
        if len(password or "") < MIN_PASSWORD:
            raise ValueError(f"A password needs at least {MIN_PASSWORD} characters.")
        with _LOCK:
            rows = self._rows()
            if any(r["username"] == username for r in rows):
                raise ValueError(f"There is already an officer {username}.")
            salt = secrets.token_bytes(16)
            row = {"username": username, "name": name, "post": post or None,
                   "salt": salt.hex(), "hash": _hash(password, salt, SCRYPT),
                   "scrypt": dict(SCRYPT), "disabled": False,
                   "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            self._write(rows + [row])
        return _public(row)

    def disable(self, username: str) -> None:
        with _LOCK:
            rows = self._rows()
            if not any(r["username"] == username for r in rows):
                raise ValueError(f"There is no officer {username}.")
            self._write([{**r, "disabled": True} if r["username"] == username else r
                         for r in rows])

    def list(self) -> list[dict]:
        return [{**_public(r), "disabled": bool(r.get("disabled"))} for r in self._rows()]

    def get(self, username: str) -> dict | None:
        """The officer, if the account exists and is not disabled."""
        row = next((r for r in self._rows() if r["username"] == username), None)
        return _public(row) if row and not row.get("disabled") else None

    def active(self) -> bool:
        """Is there anyone who could sign in?"""
        return any(not r.get("disabled") for r in self._rows())

    # ------------------------------------------------------------------ sign in
    def verify(self, username: str, password: str) -> dict | None:
        """The officer for a right password, None for a wrong one or an unknown or
        disabled account. Raises `Locked` while the account is locked."""
        key = (str(self.path), username)
        now = self.clock()
        with _LOCK:
            fails, until = _FAILS.get(key, (0, 0.0))
            if until > now:
                raise Locked(f"Too many wrong passwords. Try again in "
                             f"{LOCK_S // 60} minutes.")
            if until:                       # the lock has run out: start counting again
                fails = 0
        row = next((r for r in self._rows() if r["username"] == username), None)
        if row is None:
            # same work as for a real account, so the reply time does not say who exists
            _hash(password or "", b"\0" * 16, SCRYPT)
            good = False
        else:
            good = hmac.compare_digest(
                _hash(password or "", bytes.fromhex(row["salt"]), row["scrypt"]), row["hash"]
            ) and not row.get("disabled")
        with _LOCK:
            if good:
                _FAILS.pop(key, None)
            elif row is not None:
                fails += 1
                _FAILS[key] = (fails, now + LOCK_S if fails >= MAX_FAILS else 0.0)
        return _public(row) if good else None
