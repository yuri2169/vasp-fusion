"""One rate limit per provider, shared by every fetcher, thread and process."""
import json
import subprocess
import sys
import threading
import time

import pytest
from pathlib import Path

from vaspfusion import chains
from vaspfusion.chains.cache import ChainCache, Fetcher
from vaspfusion.chains.ratelimit import RateLimiter

from test_cache import Clock, Scripted, get

ROOT = Path(__file__).resolve().parents[2]
HOST = "api.example.com"


def limiter(tmp_path, clock: Clock) -> RateLimiter:
    return RateLimiter(tmp_path / "rate.duckdb", clock=clock.now, sleep=clock.sleep)


def test_two_limiters_on_one_file_book_slots_one_after_another(tmp_path):
    clock = Clock()
    a, b = limiter(tmp_path, clock), limiter(tmp_path, clock)

    def booked(who: RateLimiter, gap: float = 0.5) -> float:
        """When the caller's slot is, without sleeping until it."""
        return round(who._book(HOST, gap) - clock.now(), 3)

    assert booked(a) == 0.0                        # the first call goes at once
    assert booked(b) == 0.5                        # the other worker's turn comes after it
    assert booked(a) == 1.0                        # ... and the first one's after both
    assert a.acquire("other.example.com", 0.5) == 0.0     # each host has its own pace
    assert a.acquire(HOST, 0.0) == 0.0             # no pace asked for, none kept


def test_fetchers_that_share_a_limiter_share_the_pace(tmp_path):
    clock = Clock()
    shared = limiter(tmp_path, clock)
    fetchers = [Fetcher(ChainCache(tmp_path / f"c{i}.duckdb"),
                        Scripted((200, {"a": 1}), (200, {"b": 1})), offline=False,
                        sleep=clock.sleep, clock=clock.now, limiter=shared,
                        min_interval={HOST: 0.25}) for i in range(2)]
    for f in fetchers:                             # as two workers on two cases would
        get(f, {"p": 1})
        get(f, {"p": 2})
    assert clock.slept == [0.25, 0.25, 0.25]       # 4 calls, 3 gaps: never two at once


def test_a_refusal_holds_every_worker_back(tmp_path):
    clock = Clock()
    shared = limiter(tmp_path, clock)
    refused = Fetcher(ChainCache(tmp_path / "a.duckdb"),
                      Scripted((429, b"slow down"), (200, {"ok": 1})), offline=False,
                      sleep=lambda s: None, clock=clock.now, limiter=shared,
                      min_interval={HOST: 0.1}, backoff=2.0)
    other = limiter(tmp_path, clock)             # another worker, same file
    get(refused)
    # the refused worker's own back-off sleep is switched off here, so the only wait is
    # the shared one: the host's next slot moved back 2 s, for whoever called next
    assert clock.slept == [2.0]
    assert other.next_at(HOST) == pytest.approx(clock.now() + 0.1)


def test_a_replay_from_the_cache_never_books_a_slot(tmp_path):
    clock = Clock()
    shared = limiter(tmp_path, clock)
    f = Fetcher(ChainCache(tmp_path / "c.duckdb"), Scripted((200, {"a": 1})), offline=False,
                sleep=clock.sleep, clock=clock.now, limiter=shared, min_interval={HOST: 5.0})
    get(f)
    booked = shared.next_at(HOST)
    for _ in range(3):
        get(f)                                     # cache hits
    assert shared.next_at(HOST) == booked and f.stats == {"hits": 3, "live": 1, "retries": 0}


def test_eight_threads_are_never_closer_than_the_gap(tmp_path):
    shared = RateLimiter(tmp_path / "rate.duckdb")
    sent: list[float] = []
    lock = threading.Lock()

    def worker():
        mine = RateLimiter(tmp_path / "rate.duckdb")     # each worker opens its own
        for _ in range(4):
            mine.acquire(HOST, 0.03)
            with lock:
                sent.append(time.time())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    start = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    sent.sort()
    assert len(sent) == 32 and sent[-1] - start >= 31 * 0.03 - 0.005
    # a caller wakes a little late, never early: over any 5 calls the pace holds
    assert all(b - a >= 4 * 0.03 - 0.01 for a, b in zip(sent, sent[4:]))
    assert shared.next_at(HOST) >= sent[-1]


_CALLER = """
import json, sys, time
from vaspfusion.chains.ratelimit import RateLimiter
limiter, sent = RateLimiter(sys.argv[1]), []
for _ in range(5):
    limiter.acquire("api.example.com", 0.05)
    sent.append(time.time())
print(json.dumps(sent))
"""


def test_three_processes_share_one_pace(tmp_path):
    RateLimiter(tmp_path / "rate.duckdb")
    procs = [subprocess.Popen([sys.executable, "-c", _CALLER, str(tmp_path / "rate.duckdb")],
                              cwd=ROOT, stdout=subprocess.PIPE, text=True) for _ in range(3)]
    sent = sorted(t for p in procs for t in json.loads(p.communicate(timeout=120)[0]))
    assert all(p.returncode == 0 for p in procs) and len(sent) == 15
    assert sent[-1] - sent[0] >= 14 * 0.05 - 0.01
    assert all(b - a >= 4 * 0.05 - 0.02 for a, b in zip(sent, sent[4:]))


def test_the_default_fetcher_is_paced_by_the_shared_limiter(tmp_path, monkeypatch):
    monkeypatch.setenv("VASPFUSION_CHAIN_CACHE", str(tmp_path / "c.duckdb"))
    monkeypatch.setenv("VASPFUSION_RATE_DB", str(tmp_path / "rate.duckdb"))
    monkeypatch.delenv("OFFLINE", raising=False)
    live = chains.default_fetcher()
    assert isinstance(live.limiter, RateLimiter) and live.limiter.path == tmp_path / "rate.duckdb"
    monkeypatch.setenv("OFFLINE", "1")
    replay = chains.default_fetcher()
    assert replay.limiter is None and replay.cache.read_only
