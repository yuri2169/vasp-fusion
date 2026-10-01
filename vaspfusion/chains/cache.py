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
import threading
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
    """DuckDB file; a connection is opened per call so the file lock is held briefly.

    `hold=True` keeps one connection open until `close()`: a long batch job (the
    discovery crawl) then pays the open/close cost once instead of per page. No
    other process can use the file meanwhile, so give such a job its own file.
    Calls are serialised by a lock, so worker threads may share one cache."""

    def __init__(self, path: Path | str | None = None, hold: bool = False):
        self.path = Path(path or os.environ.get("VASPFUSION_CHAIN_CACHE") or DEFAULT_CACHE)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._held = None
        with self._con() as con:
            con.execute(_DDL)
        if hold:
            self._held = self._con()

    def close(self) -> None:
        with self._lock:
            if self._held is not None:
                self._held.close()
                self._held = None

    def _exec(self, sql: str, params: list, fetch: bool = False):
        with self._lock:
            if self._held is not None:
                cur = self._held.execute(sql, params)
                return cur.fetchone() if fetch else None
            with self._con() as con:
                cur = con.execute(sql, params)
                return cur.fetchone() if fetch else None

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
        row = self._exec(
            "SELECT raw_json, sha256 FROM chain_cache WHERE chain=? AND address=? "
            "AND direction=? AND query=?", [chain, address, direction, query], fetch=True)
        return (row[0], row[1]) if row else None

    def put(self, chain: str, address: str, direction: str, query: str, raw: bytes) -> str:
        sha = hashlib.sha256(raw).hexdigest()
        self._exec("INSERT OR REPLACE INTO chain_cache VALUES (?, ?, ?, ?, ?, ?, ?)",
                   [chain, address, direction, query,
                    datetime.now(timezone.utc).replace(tzinfo=None), sha, raw.decode()])
        return sha

    def count(self) -> int:
        return self._exec("SELECT count(*) FROM chain_cache", [], fetch=True)[0]


class LayeredCache:
    """A cache of its own on top of older ones: a page is read from the first cache
    that holds it, and a newly fetched page is written to `own` only. A batch job can
    then reuse what the main cache already has without growing it."""

    def __init__(self, own: ChainCache, *older: ChainCache):
        self.own, self.older = own, older

    def get(self, chain: str, address: str, direction: str, query: str):
        for cache in (self.own, *self.older):
            hit = cache.get(chain, address, direction, query)
            if hit:
                return hit
        return None

    def put(self, chain: str, address: str, direction: str, query: str, raw: bytes) -> str:
        return self.own.put(chain, address, direction, query, raw)

    def count(self) -> int:
        return sum(c.count() for c in (self.own, *self.older))

    def close(self) -> None:
        for c in (self.own, *self.older):
            c.close()


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
        self._lock = threading.Lock()   # worker threads share one fetcher (discovery crawl)
        self.stats = {"hits": 0, "live": 0, "retries": 0}
        self.trail: list[dict] = []   # per page: query, sha256, source (for provenance)

    @property
    def offline(self) -> bool:
        return offline_mode() if self._offline is None else self._offline

    def _throttle(self, host: str) -> None:
        gap = self.min_interval.get(host, 0.0)
        with self._lock:                # each caller books the next free slot, then waits
            now = self.clock()
            last = self._last_call.get(host)
            at = now if not gap or last is None else max(now, last + gap)
            self._last_call[host] = at
        if at > now:
            self.sleep(at - now)

    def _count(self, key: str) -> None:
        with self._lock:
            self.stats[key] += 1

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
                self._count("hits")
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
                self._count("retries")
                self.sleep(self.backoff * 2 ** attempt)
                continue
            sha = self.cache.put(chain, address, direction, query, body)
            self._count("live")
            self.trail.append({"query": query, "sha256": sha, "source": "live"})
            return data
        raise AssertionError("unreachable")
