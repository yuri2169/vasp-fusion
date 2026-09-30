"""Cache-first fetcher: every chain request goes through `Fetcher.get_json`.

* Hit: the stored raw JSON is returned (its SHA-256 is re-checked).
* Miss: the request goes live (per-host throttle, exponential backoff on 429/5xx
  and on bodies the provider marks `Retryable`); the body is validated by the
  provider's `check` and only then stored, with its SHA-256.
* OFFLINE=1: a miss raises `CacheMiss`. The transport is never called.

Rows are keyed by (chain, address, direction, query); `query` is the URL plus
the sorted params with API keys removed, so a cached page never holds a key and
a replay is byte-identical. Paging cursors (TronGrid fingerprints) are part of
the query, so page N+1 is found from the cached page N.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import duckdb

from .base import CacheMiss, ProviderError, Retryable
from .http import ROOT, Transport

DEFAULT_CACHE = ROOT / "data" / "chain_cache.duckdb"
SECRET_PARAMS = frozenset({"apikey", "api_key", "key", "token"})

_DDL = """
CREATE TABLE IF NOT EXISTS chain_cache (
    chain      VARCHAR NOT NULL,
    address    VARCHAR NOT NULL,
    direction  VARCHAR NOT NULL,
    query      VARCHAR NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    sha256     VARCHAR NOT NULL,
    raw_json   VARCHAR NOT NULL,
    PRIMARY KEY (chain, address, direction, query)
)"""


def offline_mode() -> bool:
    return os.environ.get("OFFLINE", "").strip().lower() in ("1", "true", "yes")


def request_key(url: str, params: dict) -> str:
    kept = sorted((k, str(v)) for k, v in params.items() if k.lower() not in SECRET_PARAMS)
    return f"{url}?{urllib.parse.urlencode(kept)}" if kept else url


class ChainCache:
    """DuckDB file; a connection is opened per call so the lock is held briefly."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or os.environ.get("VASPFUSION_CHAIN_CACHE") or DEFAULT_CACHE)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as con:
            con.execute(_DDL)

    def _con(self, read_only: bool = False, wait_s: float = 30.0):
        """DuckDB allows one writing process per file. If the API server and a CLI
        run at once, the loser waits for the lock instead of failing the fetch."""
        deadline = time.monotonic() + wait_s
        while True:
            try:
                return duckdb.connect(str(self.path), read_only=read_only)
            except duckdb.IOException as e:
                if "lock" not in str(e).lower() or time.monotonic() > deadline:
                    raise
                time.sleep(0.05)

    def get(self, chain: str, address: str, direction: str, query: str) -> tuple[str, str] | None:
        with self._con() as con:
            row = con.execute(
                "SELECT raw_json, sha256 FROM chain_cache WHERE chain=? AND address=? "
                "AND direction=? AND query=?", [chain, address, direction, query]).fetchone()
        return (row[0], row[1]) if row else None

    def put(self, chain: str, address: str, direction: str, query: str, raw: bytes) -> str:
        sha = hashlib.sha256(raw).hexdigest()
        with self._con() as con:
            con.execute("INSERT OR REPLACE INTO chain_cache VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [chain, address, direction, query,
                         datetime.now(timezone.utc).replace(tzinfo=None), sha, raw.decode()])
        return sha

    def count(self) -> int:
        with self._con() as con:
            return con.execute("SELECT count(*) FROM chain_cache").fetchone()[0]


class Fetcher:
    def __init__(self, cache: ChainCache, transport: Transport | None = None,
                 offline: bool | None = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 min_interval: dict[str, float] | None = None,
                 max_retries: int = 5, backoff: float = 1.0, refresh: bool = False):
        self.cache = cache
        self.refresh = refresh  # True: skip cache reads (still writes), i.e. re-fetch live
        self.transport = transport
        self._offline = offline
        self.sleep, self.clock = sleep, clock
        self.min_interval = dict(min_interval or {})
        self.max_retries, self.backoff = max_retries, backoff
        self._last_call: dict[str, float] = {}
        self.stats = {"hits": 0, "live": 0, "retries": 0}
        self.trail: list[dict] = []   # per page: query, sha256, source (for provenance)

    @property
    def offline(self) -> bool:
        return offline_mode() if self._offline is None else self._offline

    def _throttle(self, host: str) -> None:
        gap = self.min_interval.get(host, 0.0)
        last = self._last_call.get(host)
        if gap and last is not None:
            wait = last + gap - self.clock()
            if wait > 0:
                self.sleep(wait)
        self._last_call[host] = self.clock()

    def get_json(self, chain: str, address: str, direction: str, url: str, params: dict,
                 headers: dict | None = None, check: Callable[[Any], None] | None = None,
                 refresh: bool = False) -> Any:
        query = request_key(url, params)
        if not (refresh or self.refresh):
            hit = self.cache.get(chain, address, direction, query)
            if hit:
                raw, sha = hit
                if hashlib.sha256(raw.encode()).hexdigest() != sha:
                    raise ProviderError(f"cache row failed its sha256 check: {query}")
                self.stats["hits"] += 1
                self.trail.append({"query": query, "sha256": sha, "source": "cache"})
                return json.loads(raw)
        if self.offline:
            raise CacheMiss(f"OFFLINE=1 and not cached: chain={chain} address={address} "
                            f"direction={direction} query={query}")
        if self.transport is None:
            raise ProviderError("no transport configured for a live fetch")

        host = urllib.parse.urlsplit(url).netloc
        for attempt in range(self.max_retries + 1):
            self._throttle(host)
            status, body = self.transport.get(url, params, headers or {})
            try:
                if status == 429 or status >= 500 or (status == 403 and b"limit" in body.lower()):
                    raise Retryable(f"HTTP {status}")
                if status != 200:
                    raise ProviderError(f"HTTP {status} from {host}: {body[:200]!r}")
                try:
                    data = json.loads(body)
                except ValueError as e:
                    raise Retryable(f"non-JSON body from {host}") from e
                if check:
                    check(data)
            except Retryable as e:
                if attempt == self.max_retries:
                    raise ProviderError(f"gave up on {host} after {attempt + 1} tries: {e}") from e
                self.stats["retries"] += 1
                self.sleep(self.backoff * 2 ** attempt)
                continue
            sha = self.cache.put(chain, address, direction, query, body)
            self.stats["live"] += 1
            self.trail.append({"query": query, "sha256": sha, "source": "live"})
            return data
        raise AssertionError("unreachable")
