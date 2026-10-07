"""Nonces of signed SAHYOG calls already received, in the desk database, so the same
signed call cannot be played a second time. A nonce is kept for longer than a
signature's timestamp stays valid, then dropped."""
from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

from .connect import connect
from .requests import DEFAULT_DB

_WRITE = threading.Lock()
KEEP_S = 900

_DDL = """
CREATE TABLE IF NOT EXISTS sahyog_nonces (
    nonce   VARCHAR PRIMARY KEY,
    seen_at TIMESTAMP NOT NULL
);
"""


class NonceStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or os.environ.get("VASPFUSION_DESK_DB") or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE, connect(self.path) as con:
            con.execute(_DDL)

    def claim(self, nonce: str, now: datetime, keep_s: int = KEEP_S) -> bool:
        """True the first time a nonce is presented, False when it was seen before."""
        at = now.replace(tzinfo=None)
        with _WRITE, connect(self.path) as con:
            con.execute("DELETE FROM sahyog_nonces WHERE seen_at < ?",
                        [at - timedelta(seconds=keep_s)])
            if con.execute("SELECT 1 FROM sahyog_nonces WHERE nonce = ?", [nonce]).fetchone():
                return False
            con.execute("INSERT INTO sahyog_nonces VALUES (?, ?)", [nonce, at])
            return True
