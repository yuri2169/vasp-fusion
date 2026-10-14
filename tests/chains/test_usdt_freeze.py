"""Reading USDT's freeze events and its "is this address frozen" call (no network: a
scripted transport answers)."""
import json

import pytest

from vaspfusion.chains import usdt_freeze as F
from vaspfusion.chains.addresses import keccak256
from vaspfusion.chains.base import ProviderError
from vaspfusion.chains.cache import ChainCache, Fetcher, request_key

A1 = "0xa614f803b6fd780986a42c78ec9c7f77e6ded13c"
A2 = "0xd337e17c5bc42b9e81ca36dcbe1076c2c094707e"


class Scripted:
    """Answers each request from `pages`, a list of (predicate on params, body)."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def get(self, url, params, headers):
        self.calls.append((url, dict(params), dict(headers)))
        return 200, json.dumps(self.answer(url, params)).encode()

    def rpc(self, url, params, headers, secret=None):
        self.calls.append((url, dict(params), dict(headers)))
        return 200, json.dumps(self.answer(url, params)).encode()


@pytest.fixture
def make(tmp_path, monkeypatch):
    monkeypatch.delenv("OFFLINE", raising=False)
    for k in ("TRONGRID_API_KEY", "ETHERSCAN_API_KEY"):
        monkeypatch.setenv(k, "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")

    def build(answer, offline=False):
        t = Scripted(answer)
        return Fetcher(ChainCache(tmp_path / "c.duckdb"), t, offline=offline,
                       sleep=lambda s: None), t
    return build


def _tron_row(addr, ts, tx, idx=0, name="AddedBlackList"):
    return {"block_number": ts // 3000, "block_timestamp": ts, "event_index": idx,
            "event_name": name, "result": {"0": addr, "_user": addr},
            "transaction_id": tx}


def test_the_selectors_and_topics_are_the_contracts_own():
    assert F.TOPIC["AddedBlackList"] == "0x" + keccak256(b"AddedBlackList(address)").hex()
    assert F.TOPIC["AddedBlackList"].startswith("0x42e16015")
    assert F.TOPIC["RemovedBlackList"].startswith("0xd7e9ec6e")
    assert F.IS_BLACKLISTED == keccak256(b"isBlackListed(address)")[:4].hex()


def test_tron_events_page_by_time_and_drop_the_overlap(make):
    rows = [_tron_row(A1, 1_000, "t1"), _tron_row(A2, 2_000, "t2"), _tron_row(A1, 3_000, "t3")]

    def answer(url, params):
        lo = int(params["min_block_timestamp"])
        page = [r for r in rows if lo <= r["block_timestamp"] <= int(params["max_block_timestamp"])]
        return {"success": True, "data": page[:2], "meta": {"page_size": len(page[:2])}}
    fetcher, t = make(answer)
    got = F.tron_events(fetcher, "AddedBlackList", until_ms=10_000, page_size=2)
    assert [(e["tx"], e["time_ms"]) for e in got] == [("t1", 1_000), ("t2", 2_000), ("t3", 3_000)]
    assert got[0]["address"].startswith("T") and got[0]["chain"] == "tron"
    assert got[0]["event"] == "AddedBlackList"
    assert all(p["event_name"] == "AddedBlackList" and p["only_confirmed"] == "true"
               for _, p, _ in t.calls)


def test_tron_events_replay_offline_from_the_cache(make, tmp_path):
    rows = [_tron_row(A1, 1_000, "t1")]
    fetcher, _ = make(lambda u, p: {"success": True, "data": rows, "meta": {}})
    live = F.tron_events(fetcher, "AddedBlackList", until_ms=5_000)
    fetcher.close()
    replay = Fetcher(ChainCache(tmp_path / "c.duckdb"), None, offline=True)
    assert F.tron_events(replay, "AddedBlackList", until_ms=5_000) == live


def test_tron_events_follow_the_fingerprint_when_one_instant_fills_a_page(make):
    same = [_tron_row(A1, 1_000, "t1"), _tron_row(A2, 1_000, "t2")]
    later = [_tron_row(A1, 1_000, "t3")]

    def answer(url, params):
        if params.get("fingerprint") == "next":
            return {"success": True, "data": later, "meta": {}}
        return {"success": True, "data": same, "meta": {"fingerprint": "next"}}
    fetcher, _ = make(answer)
    got = F.tron_events(fetcher, "AddedBlackList", until_ms=5_000, page_size=2)
    assert [e["tx"] for e in got] == ["t1", "t2", "t3"]


def _log(addr, block, tx, idx=0, topic="AddedBlackList"):
    return {"address": F.ETH_USDT, "topics": [F.TOPIC[topic]],
            "data": "0x" + "0" * 24 + addr[2:], "blockNumber": hex(block),
            "timeStamp": hex(1_500_000_000 + block), "logIndex": hex(idx),
            "transactionHash": tx}


def test_eth_logs_page_by_block_and_decode_the_address(make):
    logs = [_log(A1, 10, "0x1"), _log(A2, 10, "0x2", 1), _log(A1, 12, "0x3")]

    def answer(url, params):
        lo, hi, n = int(params["fromBlock"]), int(params["toBlock"]), int(params["page"])
        page = [x for x in logs if lo <= int(x["blockNumber"], 16) <= hi]
        return {"status": "1", "message": "OK", "result": page[(n - 1) * 2:n * 2]}
    fetcher, t = make(answer)
    got = F.eth_logs(fetcher, "AddedBlackList", to_block=100, page_size=2)
    assert [(e["tx"], e["address"], e["block"]) for e in got] == \
        [("0x1", A1, 10), ("0x2", A2, 10), ("0x3", A1, 12)]
    assert got[0]["time_ms"] == (1_500_000_000 + 10) * 1000
    assert {p["topic0"] for _, p, _ in t.calls} == {F.TOPIC["AddedBlackList"]}


def test_eth_logs_refuse_a_block_past_the_explorers_window(make):
    def answer(url, params):                 # block 10 never runs out
        n = int(params["page"])
        return {"status": "1", "message": "OK",
                "result": [_log(A1, 10, f"0x{n}{i}", i) for i in range(5_000)]}
    fetcher, _ = make(answer)
    with pytest.raises(ProviderError, match="in block 10"):
        F.eth_logs(fetcher, "AddedBlackList", to_block=100, page_size=5_000)


def test_eth_no_records_is_an_empty_list(make):
    fetcher, _ = make(lambda u, p: {"status": "0", "message": "No records found", "result": []})
    assert F.eth_logs(fetcher, "RemovedBlackList", to_block=100) == []


def test_is_blacklisted_calls_the_contract_on_each_chain(make):
    def answer(url, params):
        if "jsonrpc" in url:
            call = json.loads(params["params"])[0]
            assert call["to"] == "0x" + F.tron_hex(F.TRON_USDT)
            assert call["data"].startswith("0x" + F.IS_BLACKLISTED)
            return {"jsonrpc": "2.0", "id": 1, "result": "0x" + "0" * 63 + "1"}
        assert params["module"] == "proxy" and params["action"] == "eth_call"
        assert params["data"] == "0x" + F.IS_BLACKLISTED + "0" * 24 + A2[2:]
        return {"jsonrpc": "2.0", "id": 1, "result": "0x" + "0" * 64}
    fetcher, _ = make(answer)
    assert F.is_blacklisted(fetcher, "tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t") is True
    assert F.is_blacklisted(fetcher, "ethereum", A2) is False


def test_the_cache_key_never_holds_a_key():
    assert "apikey" not in request_key(F.ETHERSCAN, {"module": "logs", "apikey": "SECRET"})


def test_a_log_index_of_zero_written_as_bare_0x(make):
    log = {**_log(A1, 10, "0x1"), "logIndex": "0x"}
    fetcher, _ = make(lambda u, p: {"status": "1", "message": "OK", "result": [log]})
    assert F.eth_logs(fetcher, "AddedBlackList", to_block=100)[0]["index"] == 0
