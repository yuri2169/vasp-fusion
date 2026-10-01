"""A long crawl holds one cache connection and fetches with several workers. The
result must not depend on either."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from test_discover_crawl import LABELS, Chain, Labels, deposit_and_sweep, ev
from tracekit import CHAIN, T0
from vaspfusion.chains.cache import ChainCache, Fetcher
from vaspfusion.discover.crawl import CrawlConfig, discover


def test_a_held_cache_keeps_one_connection_and_persists_on_close(tmp_path):
    path = tmp_path / "c.duckdb"
    cache = ChainCache(path, hold=True)
    sha = cache.put("tron", "A", "both", "q1", b'{"a": 1}')
    assert cache.get("tron", "A", "both", "q1") == ('{"a": 1}', sha)
    assert cache.count() == 1
    cache.close()
    assert ChainCache(path).get("tron", "A", "both", "q1") == ('{"a": 1}', sha)
    cache.close()                      # closing twice is harmless


def test_a_held_cache_is_safe_from_many_threads(tmp_path):
    cache = ChainCache(tmp_path / "c.duckdb", hold=True)

    def work(i):
        cache.put("tron", f"A{i}", "both", "q", json.dumps({"i": i}).encode())
        return cache.get("tron", f"A{i}", "both", "q")[0]

    with ThreadPoolExecutor(8) as pool:
        got = list(pool.map(work, range(200)))
    assert got == [json.dumps({"i": i}) for i in range(200)] and cache.count() == 200
    cache.close()


class CountingTransport:
    def __init__(self):
        self.lock, self.calls, self.times = threading.Lock(), 0, []

    def get(self, url, params, headers):
        with self.lock:
            self.calls += 1
        return 200, json.dumps({"url": url}).encode()


def test_the_fetcher_counts_and_throttles_correctly_under_threads(tmp_path):
    transport = CountingTransport()
    slept = []
    f = Fetcher(ChainCache(tmp_path / "c.duckdb", hold=True), transport, offline=False,
                sleep=slept.append, clock=lambda: 0.0, min_interval={"h.example.com": 0.5})
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda i: f.get_json("tron", f"A{i}", "both",
                                           f"https://h.example.com/{i}", {}), range(40)))
    assert transport.calls == 40 and f.stats["live"] == 40 and len(f.trail) == 40
    # with a frozen clock every request after the first is scheduled one gap later
    assert sorted(slept) == [0.5 * i for i in range(1, 40)]


def crawl(workers):
    rows, gas = [], {}
    for i in range(30):
        rows += deposit_and_sweep(10 * i + 1, f"D{i:02d}", "HOT" if i % 3 else "BHOT", i)
        gas[f"D{i:02d}"] = [ev("GASA" if i % 2 else "STATION", i + 4)]
    chain = Chain(rows, gas)
    result = discover(CHAIN, chain, chain, Labels(LABELS),
                      CrawlConfig(window_start=T0), workers=workers)
    return result, chain


def test_workers_do_not_change_the_result():
    one, _ = crawl(1)
    many, chain = crawl(6)
    assert many.findings == one.findings and many.stats == one.stats
    assert many.stations == one.stations and many.totals == one.totals
    assert len(one.findings) == 30
    # the workers warmed every candidate; the gas listing still only for fired addresses
    assert set(chain.gas_calls) == {f.address for f in many.findings}
