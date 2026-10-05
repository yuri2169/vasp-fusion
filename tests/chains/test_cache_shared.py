"""Workers share one response cache; a replay opens it read-only and keeps it open."""
import threading
import time

import pytest

from vaspfusion.chains.base import CacheMiss, ProviderError
from vaspfusion.chains.cache import ChainCache, Fetcher

from test_cache import Scripted, get, mk


def replay_of(path) -> Fetcher:
    return Fetcher(ChainCache(path, read_only=True), None, offline=True)


def test_a_page_one_case_fetched_is_a_hit_for_the_next_case(tmp_path):
    t = Scripted((200, {"data": [1]}))
    first = Fetcher(ChainCache(tmp_path / "c.duckdb"), t, offline=False)
    second = Fetcher(ChainCache(tmp_path / "c.duckdb"), t, offline=False)   # another worker
    assert get(first) == get(second) == {"data": [1]}
    assert len(t.calls) == 1 and second.stats == {"hits": 1, "live": 0, "retries": 0}


def test_a_replay_cache_reads_and_is_never_written(tmp_path):
    f, _ = mk(tmp_path, Scripted((200, {"data": [1]})))
    get(f)
    replay = replay_of(tmp_path / "c.duckdb")
    assert get(replay) == {"data": [1]} and replay.cache.count() == 1
    with pytest.raises(CacheMiss):
        get(replay, {"limit": 3})
    with pytest.raises(ProviderError, match="not written"):
        replay.cache.put("tron", "Tabc", "both", "q", b"{}")
    replay.close()
    assert get(replay) == {"data": [1]}             # closed is not broken: it opens again


def test_a_replay_of_a_cache_that_is_not_there_is_a_miss_and_creates_nothing(tmp_path):
    replay = replay_of(tmp_path / "none.duckdb")
    with pytest.raises(CacheMiss):
        get(replay)
    assert replay.cache.count() == 0 and not (tmp_path / "none.duckdb").exists()


def test_a_writer_waits_for_a_replay_in_this_process_instead_of_failing(tmp_path):
    f, _ = mk(tmp_path, Scripted((200, {"data": [1]}), (200, {"data": [2]})))
    get(f)
    replay = replay_of(tmp_path / "c.duckdb")
    get(replay)                                    # the read-only connection is now held
    threading.Timer(0.3, replay.close).start()
    start = time.monotonic()
    assert get(f, {"limit": 5}) == {"data": [2]}    # a write: waits until the replay lets go
    assert time.monotonic() - start >= 0.25


def test_a_replay_lets_go_of_the_file_when_its_fetcher_is_dropped(tmp_path):
    f, _ = mk(tmp_path, Scripted((200, {"data": [1]}), (200, {"data": [2]})))
    get(f)
    replay = replay_of(tmp_path / "c.duckdb")
    get(replay)
    del replay
    start = time.monotonic()
    assert get(f, {"limit": 5}) == {"data": [2]}
    assert time.monotonic() - start < 5


def test_many_replays_read_one_cache_at_once(tmp_path):
    f, _ = mk(tmp_path, Scripted((200, {"data": [1]})))
    get(f)
    errors = []

    def read():
        try:
            for _ in range(20):
                replay = replay_of(tmp_path / "c.duckdb")
                assert get(replay) == {"data": [1]}
                replay.close()
        except Exception as e:      # noqa: BLE001 - the test reports every failure
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=read) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
