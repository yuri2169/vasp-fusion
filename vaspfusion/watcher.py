"""The background watcher: watched wallets are traced again on a schedule.

Off unless VASPFUSION_WATCH_INTERVAL is set (seconds between two checks of one wallet):
the offline demo cannot reach a chain, so there it stays off and a wallet is checked
when the officer asks. A scheduled check is the same as "Check now": the wallet's trace
is queued like any other, reads the chain afresh through the shared rate limiter, and
what is new against the baseline (a transfer, an exchange, a tagged address, a higher
risk class) is a change with the time of the trace that found it (watch.py).
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

MIN_PAUSE_S = 1.0
MAX_PAUSE_S = 30.0


def every() -> int:
    """Seconds between two scheduled checks of one wallet; 0 = the watcher is off."""
    try:
        return max(0, int(float(os.environ.get("VASPFUSION_WATCH_INTERVAL") or 0)))
    except ValueError:
        return 0


def _at(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def due(entries: list[dict], now: datetime, every_s: int) -> list[dict]:
    """The watched wallets whose last scheduled check is `every_s` old or older (or that
    never had one), longest-waiting first."""
    if every_s <= 0:
        return []
    limit = now - timedelta(seconds=every_s)
    waiting = [e for e in entries
               if _at(e.get("auto_checked_at")) is None or _at(e["auto_checked_at"]) <= limit]
    return sorted(waiting, key=lambda e: e.get("auto_checked_at") or "")


class Watcher(threading.Thread):
    """Calls `tick()` again and again until stopped. A tick that raises is forgotten:
    the next one runs all the same."""

    def __init__(self, tick: Callable[[], object], every_s: int):
        super().__init__(daemon=True, name="watcher")
        self.tick, self.every_s = tick, every_s
        self.pause = min(MAX_PAUSE_S, max(MIN_PAUSE_S, every_s / 4))
        self._halt = threading.Event()
        self.last_run_at: datetime | None = None

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - a store that is busy or missing; try again
                pass
            self.last_run_at = datetime.now(timezone.utc)
            self._halt.wait(self.pause)

    def stop(self) -> None:
        self._halt.set()
