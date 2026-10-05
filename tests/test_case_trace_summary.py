"""`trace_summary` on the recorded demo wallets: the counts add up against the case's own
graph, and they are the same figures every time (pinned below, as first read from the
recorded responses on 5 Oct 2026)."""
import pytest

from demokit import SPECS, run_demo
from vaspfusion import provenance as P
from vaspfusion.api import schemas as S
from vaspfusion.explain.case_file import case_file_text

# case -> (transfers seen, followed, wallets read, wallets followed, wallets not followed)
PINNED = {
    "tron-coindcx": (160, 8, 3, 2, 13),
    "eth-bitget": (20, 5, 1, 1, 7),
    "tron-ofac": (39, 15, 3, 3, 15),
    "tron-htx-coindcx": (25, 7, 3, 3, 11),
    "tron-abstain": (655, 23, 14, 10, 23),
    "eth-abstain": (27, 7, 6, 6, 10),
    "eth-bridge": (494, 42, 9, 8, 70),
    "btc-htx": (4, 4, 1, 1, 3),
    "bnb-coindcx": (384, 23, 4, 1, 13),
    "sol-okx": (7, 5, 1, 1, 3),
    "polygon-bitget": (7, 4, 1, 1, 3),
    "tron-terror-link": (672, 152, 11, 9, 61),
}


@pytest.fixture(scope="module")
def cases(tmp_path_factory):
    root = tmp_path_factory.mktemp("summary")
    return {case_id: run_demo(case_id, root / f"{case_id}.duckdb") for case_id in SPECS}


@pytest.mark.parametrize("case_id", list(SPECS))
def test_the_counts_add_up_against_the_graph(cases, case_id):
    case = cases[case_id]
    s = S.TraceSummary.model_validate(case["trace_summary"]).model_dump()
    assert s["transfers_followed"] <= s["transfers_seen"]
    # what was followed is what is drawn: one row for each transfer on the graph
    assert s["transfers_followed"] == len({(e["tx_hash"], e["source"], e["target"], e["asset"],
                                            e["amount"]) for e in case["graph"]["edges"]})
    assert s["wallets_followed"] <= s["wallets_read"]
    assert s["wallets_not_followed"] == sum(r["count"] for r in s["not_followed"])
    on_graph = {n["id"] for n in case["graph"]["nodes"]}
    listed = [w for r in s["not_followed"] if r["reason"] not in ("dust", "other_chain")
              for w in r["wallet_ids"]]
    assert len(listed) == len(set(listed)) and set(listed) <= on_graph
    # every wallet on the graph was followed, or is listed under one reason
    assert s["wallets_followed"] + len(listed) == len(on_graph)
    off_graph = [w for r in s["not_followed"] if r["reason"] in ("dust", "other_chain")
                 for w in r["wallet_ids"]]
    assert not set(off_graph) & on_graph
    assert s["wallets_seen"] >= len(on_graph)


@pytest.mark.parametrize("case_id", list(SPECS))
def test_the_recorded_cases_give_stable_figures(cases, case_id):
    s = cases[case_id]["trace_summary"]
    got = (s["transfers_seen"], s["transfers_followed"], s["wallets_read"],
           s["wallets_followed"], s["wallets_not_followed"])
    assert got == PINNED[case_id]


def test_the_summary_is_content_but_not_a_finding(cases):
    case = dict(cases["tron-coindcx"])
    bare = {**case, "trace_summary": None}
    assert P.findings_sha256(bare) == P.findings_sha256(case)
    assert P.content_sha256(bare) != P.content_sha256(case)


def test_the_case_file_prints_the_same_line(cases):
    case = cases["tron-coindcx"]
    text = " ".join(case_file_text(case).split())
    assert case["trace_summary"]["text"] in text
