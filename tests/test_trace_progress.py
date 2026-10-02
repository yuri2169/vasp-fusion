"""What a running trace reports while it works (U2): the officer watching a case sees how
many wallets and transfers have been read, how far out the trace is, and which labelled
wallets it has reached. Reporting never changes the result."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demokit import run_demo  # noqa: E402
from tracekit import CHAIN, ToyLabels, ToyProvider, tx  # noqa: E402
from vaspfusion.explain.progress import progress_sentence  # noqa: E402
from vaspfusion.trace import TraceConfig, trace  # noqa: E402

LABELS = {"HOT": ("ExA", "exchange"), "BAD": ("OFAC SDN", "sanctioned")}

# F funds S; S pays M1 and M2; M1 forwards to the exchange, M2 to a sanctioned address.
TRANSFERS = [
    tx(1, "F", "S", 200, 0),
    tx(2, "S", "M1", 120, 10),
    tx(3, "S", "M2", 80, 11),
    tx(4, "M1", "HOT", 120, 20),
    tx(5, "M2", "BAD", 80, 25),
]


def watch(transfers=TRANSFERS, labels=LABELS, **cfg):
    seen: list[dict] = []
    result = trace("S", CHAIN, ToyProvider(transfers), ToyLabels(labels), TraceConfig(**cfg),
                   on_progress=seen.append)
    return result, seen


def test_it_reports_as_it_goes_and_ends_with_what_was_read():
    _, seen = watch()
    assert len(seen) >= 4
    last = seen[-1]
    assert last["asset"] == "USDT"
    assert last["hop"] == 2
    # S, M1 and M2 were read. HOT and BAD are labelled, so the trace stops there; F is one
    # hop back, which is as far as the inbound side looks, so its own listing is not read
    assert last["wallets_read"] == 3
    # S's 2 outgoing, M1's 1, M2's 1, S's 1 incoming
    assert last["transfers_read"] == 5
    assert last["reached"] == [
        {"entity": "ExA", "category": "exchange", "hop": 2},
        {"entity": "OFAC SDN", "category": "sanctioned", "hop": 2},
    ]


def test_the_money_is_followed_out_first_then_the_funders_are_read():
    _, seen = watch()
    phases = [p["phase"] for p in seen]
    assert phases[0] == "outbound" and phases[-1] == "inbound"
    assert phases == sorted(phases, key=["outbound", "inbound"].index)


def test_the_counts_only_grow():
    _, seen = watch()
    for before, after in zip(seen, seen[1:]):
        assert after["wallets_read"] >= before["wallets_read"]
        assert after["transfers_read"] >= before["transfers_read"]
        assert len(after["reached"]) >= len(before["reached"])


def test_each_report_is_its_own_snapshot():
    _, seen = watch()
    first = dict(seen[0], reached=list(seen[0]["reached"]))
    seen[-1]["reached"].append("changed later")
    assert seen[0] == first


def test_a_labelled_wallet_is_named_once_however_many_transfers_reach_it():
    extra = TRANSFERS + [tx(6, "S", "M3", 50, 12), tx(7, "M3", "HOT", 50, 30)]
    _, seen = watch(extra)
    assert [r["entity"] for r in seen[-1]["reached"]].count("ExA") == 1


def test_reporting_does_not_change_the_trace():
    silent = trace("S", CHAIN, ToyProvider(TRANSFERS), ToyLabels(LABELS), TraceConfig())
    watched, _ = watch()
    assert watched.stopped == silent.stopped
    assert [(e.transfer.tx_hash, e.traced, e.hop) for e in watched.edges] == \
           [(e.transfer.tx_hash, e.traced, e.hop) for e in silent.edges]
    assert {k: (n.state, n.received) for k, n in watched.nodes.items()} == \
           {k: (n.state, n.received) for k, n in silent.nodes.items()}


def test_a_listener_that_breaks_does_not_break_the_trace():
    def broken(_):
        raise RuntimeError("the screen went away")
    result = trace("S", CHAIN, ToyProvider(TRANSFERS), ToyLabels(LABELS), TraceConfig(),
                   on_progress=broken)
    assert ("outbound", "HOT") in result.nodes


def test_a_wallet_that_sent_nothing_still_reports_that_it_was_read():
    _, seen = watch([tx(1, "F", "S", 200, 0)])
    assert seen and seen[-1]["wallets_read"] >= 1 and seen[-1]["reached"] == []


# ---------------------------------------------------------------- a real wallet
def test_a_real_case_reports_its_trace_then_that_it_is_being_checked(tmp_path):
    seen: list[dict] = []
    watched = run_demo("tron-coindcx", tmp_path / "a.duckdb", on_progress=seen.append)
    silent = run_demo("tron-coindcx", tmp_path / "b.duckdb")
    assert [p["phase"] for p in seen][-1] == "checking"
    assert {"outbound", "inbound"} <= {p["phase"] for p in seen}
    last = seen[-1]
    assert last["asset"] == "USDT" and last["wallets_read"] >= 2 and last["transfers_read"] >= 8
    assert {"entity": "CoinDCX", "category": "exchange", "hop": 1} in last["reached"]
    # the result is the same, to the digest
    assert watched["provenance"]["findings_sha256"] == silent["provenance"]["findings_sha256"]
    assert watched["provenance"]["content_sha256"] == silent["provenance"]["content_sha256"]


def test_progress_is_the_state_of_a_run_and_no_part_of_the_result(tmp_path):
    """A stored case is a result with digests; what a run had read at some moment is not in
    them, so a case traced before this field existed still verifies."""
    from vaspfusion import provenance as P
    case = run_demo("tron-coindcx", tmp_path / "a.duckdb")
    bare = {k: v for k, v in case.items() if k != "progress"}
    watching = {**case, "progress": {"phase": "outbound", "asset": "USDT", "hop": 1,
                                     "wallets_read": 2, "transfers_read": 9, "reached": [],
                                     "message": "x"}}
    assert P.content_sha256(bare) == P.content_sha256(case) == P.content_sha256(watching)
    assert P.findings_sha256(bare) == P.findings_sha256(case) == P.findings_sha256(watching)
    assert case["provenance"]["content_sha256"] == P.content_sha256(bare)


# ---------------------------------------------------------------- the sentence
def snapshot(**over):
    base = {"phase": "outbound", "asset": "USDT", "hop": 2, "wallets_read": 5,
            "transfers_read": 214, "reached": []}
    return {**base, **over}


@pytest.mark.parametrize("progress, sentence", [
    (snapshot(phase="reading", asset=None, hop=0, wallets_read=0, transfers_read=0),
     "Reading the wallet's transfers on Tron."),
    (snapshot(),
     "Following the money on Tron: 214 USDT transfers of 5 wallets read, 2 hops out."),
    (snapshot(hop=1, wallets_read=1, transfers_read=1),
     "Following the money on Tron: 1 USDT transfer of 1 wallet read, 1 hop out."),
    (snapshot(transfers_read=1234, reached=[{"entity": "CoinDCX", "category": "exchange", "hop": 1}]),
     "Following the money on Tron: 1,234 USDT transfers of 5 wallets read, 2 hops out. "
     "Reached so far: CoinDCX."),
    (snapshot(phase="inbound", reached=[
        {"entity": "CoinDCX", "category": "exchange", "hop": 1},
        {"entity": "OFAC SDN", "category": "sanctioned", "hop": 2},
        {"entity": "Across Protocol", "category": "bridge", "hop": 1}]),
     "Followed the money 2 hops out on Tron (214 USDT transfers of 5 wallets). Now reading who "
     "funded the wallet. Reached so far: CoinDCX, OFAC SDN (sanctioned), Across Protocol (bridge)."),
    (snapshot(phase="checking", wallets_read=7, transfers_read=230,
              reached=[{"entity": "CoinDCX", "category": "exchange", "hop": 1}]),
     "Read 230 USDT transfers of 7 wallets on Tron. Now checking the result: each exchange "
     "that would be named is traced again without its label. Reached: CoinDCX."),
    (snapshot(phase="checking", asset=None, hop=0, wallets_read=1, transfers_read=0),
     "Read the wallet's transfers on Tron. Now checking the result."),
])
def test_the_sentence_the_officer_reads(progress, sentence):
    assert progress_sentence("tron", progress) == sentence
