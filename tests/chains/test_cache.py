import hashlib
import json

import duckdb
import pytest

from vaspfusion.chains.base import CacheMiss, ProviderError, Retryable
from vaspfusion.chains.cache import ChainCache, Fetcher, request_key

URL = "https://api.example.com/v1/x"


class Scripted:
    """Transport that answers from a list of (status, body) and records the calls."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def get(self, url, params, headers):
        self.calls.append((url, dict(params), dict(headers)))
        status, body = self.answers.pop(0)
        return status, body if isinstance(body, bytes) else json.dumps(body).encode()


class Clock:
    def __init__(self):
        self.t = 100.0
        self.slept = []

    def sleep(self, s):
        self.slept.append(round(s, 3))
        self.t += s

    def now(self):
        return self.t


def mk(tmp_path, transport, offline=False, **kw):
    clock = Clock()
    f = Fetcher(ChainCache(tmp_path / "c.duckdb"), transport, offline=offline,
                sleep=clock.sleep, clock=clock.now, **kw)
    return f, clock


def get(f, params=None, **kw):
    return f.get_json("tron", "Tabc", "both", URL, params or {"limit": 2}, **kw)


def test_request_key_sorted_and_secret_free():
    k = request_key(URL, {"b": 2, "apikey": "SECRET", "a": 1})
    assert k == URL + "?a=1&b=2"
    assert "SECRET" not in k


def test_miss_then_hit(tmp_path):
    t = Scripted((200, {"data": [1, 2]}))
    f, _ = mk(tmp_path, t)
    assert get(f) == {"data": [1, 2]}
    assert get(f) == {"data": [1, 2]}
    assert len(t.calls) == 1
    assert f.stats == {"hits": 1, "live": 1}
    assert [e["source"] for e in f.trail] == ["live", "cache"]


def test_stored_raw_and_sha256(tmp_path):
    body = b'{"data": [1, 2]}'
    f, _ = mk(tmp_path, Scripted((200, body)))
    get(f)
    con = duckdb.connect(str(tmp_path / "c.duckdb"), read_only=True)
    raw, sha, query = con.execute("select raw_json, sha256, query from chain_cache").fetchone()
    assert raw == body.decode()
    assert sha == hashlib.sha256(body).hexdigest()
    assert query == URL + "?limit=2"


def test_apikey_never_stored(tmp_path):
    f, _ = mk(tmp_path, Scripted((200, {"ok": 1})))
    get(f, {"apikey": "SECRET-KEY", "page": 1}, headers={"TRON-PRO-API-KEY": "SECRET-HDR"})
    con = duckdb.connect(str(tmp_path / "c.duckdb"), read_only=True)
    dump = json.dumps(con.execute("select * from chain_cache").fetchall(), default=str)
    assert "SECRET" not in dump
    assert "SECRET" not in json.dumps(f.trail)


def test_offline_miss_raises_and_never_calls_transport(tmp_path):
    t = Scripted()
    f, _ = mk(tmp_path, t, offline=True)
    with pytest.raises(CacheMiss) as e:
        get(f)
    assert "tron" in str(e.value) and "Tabc" in str(e.value) and "limit=2" in str(e.value)
    assert t.calls == []


def test_offline_hit_after_live(tmp_path):
    f, _ = mk(tmp_path, Scripted((200, {"a": 1})))
    get(f)
    t2 = Scripted()
    f2, _ = mk(tmp_path, t2, offline=True)
    assert get(f2) == {"a": 1}
    assert t2.calls == []


def test_offline_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFLINE", "1")
    t = Scripted()
    f = Fetcher(ChainCache(tmp_path / "c.duckdb"), t)
    with pytest.raises(CacheMiss):
        get(f)
    assert t.calls == []


def test_refresh_bypasses_cache(tmp_path):
    t = Scripted((200, {"v": 1}), (200, {"v": 2}))
    f, _ = mk(tmp_path, t)
    assert get(f) == {"v": 1}
    assert get(f, refresh=True) == {"v": 2}
    assert get(f) == {"v": 2}


def test_429_backs_off_then_succeeds(tmp_path):
    t = Scripted((429, b"slow down"), (200, {"ok": 1}))
    f, clock = mk(tmp_path, t, backoff=1.0)
    assert get(f) == {"ok": 1}
    assert clock.slept == [1.0]


def test_5xx_gives_up(tmp_path):
    t = Scripted(*[(500, b"boom")] * 3)
    f, clock = mk(tmp_path, t, max_retries=2, backoff=1.0)
    with pytest.raises(ProviderError, match="gave up"):
        get(f)
    assert clock.slept == [1.0, 2.0]
    assert f.stats["live"] == 0


def test_4xx_is_fatal_and_not_cached(tmp_path):
    f, _ = mk(tmp_path, Scripted((400, b"bad request"), (200, {"ok": 1})))
    with pytest.raises(ProviderError, match="HTTP 400"):
        get(f)
    assert get(f) == {"ok": 1}  # nothing was cached by the failure


def test_check_retryable_and_fatal(tmp_path):
    def check(body):
        if body.get("rate"):
            raise Retryable("rate limited")
        if body.get("err"):
            raise ProviderError(body["err"])

    t = Scripted((200, {"rate": 1}), (200, {"err": "nope"}), (200, {"ok": 1}))
    f, clock = mk(tmp_path, t, backoff=0.5)
    with pytest.raises(ProviderError, match="nope"):
        get(f, check=check)
    assert clock.slept == [0.5]
    assert get(f, check=check) == {"ok": 1}  # the error body was not cached


def test_throttle_per_host(tmp_path):
    t = Scripted((200, {"a": 1}), (200, {"b": 1}))
    f, clock = mk(tmp_path, t, min_interval={"api.example.com": 0.25})
    get(f, {"p": 1})
    get(f, {"p": 2})
    assert clock.slept == [0.25]


def test_corrupted_cache_row_detected(tmp_path):
    f, _ = mk(tmp_path, Scripted((200, {"a": 1})))
    get(f)
    con = duckdb.connect(str(tmp_path / "c.duckdb"))
    con.execute("update chain_cache set raw_json = '{\"a\": 2}'")
    con.close()
    with pytest.raises(ProviderError, match="sha256"):
        get(f)
