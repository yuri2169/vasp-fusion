"""A real wallet whose money left Ethereum through Stargate, replayed with no network.

Recorded live on 8 Oct 2026 (scripts/record_crosschain_case.py): every chain response,
every answer of LayerZero Scan and every label row the trace read. The wallet was picked
from recent deposits into Stargate's pool because most of what it sent crossed; nothing
is claimed about its owner. artifacts/crosschain/eth-stargate.json holds what the live
trace found, and this replay must find the same."""
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from vaspfusion.cases import run_case, trace_provider
from vaspfusion.chains.cache import ChainCache, Fetcher, request_key
from vaspfusion.labels.lookup import Label
from vaspfusion.trace import TraceConfig

ROOT = Path(__file__).resolve().parents[1]
RECORDED = json.loads((ROOT / "tests" / "fixtures" / "crosschain" / "eth-stargate.json")
                      .read_text())
FOUND = json.loads((ROOT / "artifacts" / "crosschain" / "eth-stargate.json").read_text())
WALLET = "0xd652d8bc3d851b18d045b9c9bbb83d1001af5ea3"


class Replay:
    def __init__(self):
        self.calls = 0

    def get(self, url, params, headers):
        key = request_key(url, params)
        assert key in RECORDED["responses"], f"not in the recording (would go live): {key}"
        self.calls += 1
        r = RECORDED["responses"][key]
        body = r["body"]
        return r["status"], (json.dumps(body) if not isinstance(body, str) else body).encode()

    def rpc(self, url, params, headers, secret=None):
        return self.get(url, params, headers)


class Labels:
    def __init__(self):
        self.rows = {k: Label.from_dict(v) for k, v in RECORDED["labels"].items()}

    def lookup_many(self, pairs):
        return {(a, c): self.rows[f"{c}:{a}"] for a, c in pairs if f"{c}:{a}" in self.rows}


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("ETHERSCAN_API_KEY", "test-key")
    mp.delenv("OFFLINE", raising=False)
    mp.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path_factory.mktemp("env") / "no.env")
    try:
        fetcher = Fetcher(ChainCache(tmp_path_factory.mktemp("sg") / "c.duckdb"), Replay(),
                          sleep=lambda s: None)
        cfg = TraceConfig(max_hops=3)
        yield run_case(WALLET, "ethereum", trace_provider("ethereum", fetcher, cfg, key="test-key"),
                       Labels(), case_id="eth-stargate", cfg=cfg, fetcher=fetcher,
                       provider_opts={"key": "test-key"},
                       now=datetime(2026, 10, 8, tzinfo=timezone.utc))
    finally:
        mp.undo()


def test_the_money_is_followed_from_ethereum_onto_arbitrum_through_stargate(case):
    assert case["chains"] == ["ethereum", "arbitrum"] == FOUND["chains"]
    followed = [c for c in case["crossings"] if c["status"] == "followed"]
    assert len(followed) == 7 and len(case["crossings"]) == 8
    assert {c["bridge"] for c in followed} == {"Stargate"}
    assert {c["matched_by"] for c in followed} == {"scan.layerzero-api.com"}
    assert {c["dest_name"] for c in followed} == {"Arbitrum"}


def test_each_crossing_is_what_the_live_trace_found(case):
    keep = ("status", "source_tx", "recipient", "payout_tx", "amount_in", "amount_out", "fee")
    assert [{k: c.get(k) for k in keep} for c in case["crossings"]] \
        == [{k: c.get(k) for k in keep} for c in FOUND["crossings"]]


def test_the_amount_that_arrived_is_read_on_arbitrum_and_the_difference_is_the_bridges_fee(case):
    for c in (c for c in case["crossings"] if c["status"] == "followed"):
        sent, arrived, fee = (Decimal(str(c[k])) for k in ("amount_in", "amount_out", "fee"))
        # the fee is held on the share of the deposit that was the wallet's traced money
        assert Decimal(0) < arrived < sent and Decimal(0) < fee <= sent - arrived
        assert fee / sent < Decimal("0.001")            # under a tenth of a percent, each time
        assert 60 <= c["seconds"] <= 600                # minutes, as the index timed it


def test_the_recipients_are_not_the_wallet_itself_and_come_from_the_message(case):
    people = {c["recipient"] for c in case["crossings"] if c["status"] == "followed"}
    assert people == {"0xb6de222daef5029f31b8fabe498d34f3c491ef85",
                      "0x0b33eba531e5a5a331a3ff9f418b8205f01c2869"}
    assert WALLET not in people


def test_no_exchange_is_named_and_the_case_says_where_the_money_went(case):
    assert (case["outcome"], case["top_vasp"]) == ("INSUFFICIENT_EVIDENCE", None)
    assert "left Ethereum through the Stargate bridge" in case["narrative"]
    assert "on Arbitrum, where the trace goes on" in case["narrative"]
    small = next(c for c in case["crossings"] if c["status"] != "followed")
    assert small["reason"] == "it is too small a part of the funds to follow"
