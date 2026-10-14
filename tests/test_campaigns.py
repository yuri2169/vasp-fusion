"""Linked complaints from stored traces: a wallet two different suspects' money reached.
One synthetic pair (built here, never shipped as data) and the recorded cases."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demokit import run_demo  # noqa: E402
from vaspfusion.campaigns import LIMIT, linked, related  # noqa: E402
from vaspfusion.labels.frozen import FreezeList  # noqa: E402

A, B = "TVictimOneAAAAAAAAAAAAAAAAAAAAAAAA", "TVictimTwoBBBBBBBBBBBBBBBBBBBBBBBB"
MULE = "TMuleCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
HOT = "TExchangeHotDDDDDDDDDDDDDDDDDDDDDD"
HUB = "TBusyServiceEEEEEEEEEEEEEEEEEEEEEE"
SCAM = "TScamListedFFFFFFFFFFFFFFFFFFFFFFF"
NONE = FreezeList({}, {})


def node(addr, hop, role="intermediary", label=None, hub=False):
    return {"id": addr, "address": addr, "chain": "tron", "role": role, "hop": hop,
            "label": label, "is_hub": hub}


def edge(src, dst, amount, tx, t="2026-03-01T10:00:00Z"):
    return {"id": tx, "source": src, "target": dst, "traced_amount": amount, "asset": "USDT",
            "direction": "outbound", "tx_hash": tx, "block_time": t}


EXCHANGE = {"category": "exchange", "entity": "CoinDCX", "kind": "hot"}
SCAM_LABEL = {"category": "scam", "entity": "Fake exchange", "label": "Fake exchange"}


def case(cid, suspect, mule_amount, *, hop_to_mule=1):
    nodes = [node(suspect, 0, "suspect"), node(MULE, hop_to_mule),
             node(HOT, 2, "exchange_hot", EXCHANGE), node(HUB, 2, "hub", hub=True),
             node(SCAM, 2, "unknown", SCAM_LABEL)]
    edges = [edge(suspect, MULE, mule_amount, f"{cid}1"), edge(MULE, HOT, 10.0, f"{cid}2"),
             edge(MULE, HUB, 5.0, f"{cid}3"), edge(MULE, SCAM, 7.0, f"{cid}4")]
    return {"id": cid, "case_ref": f"FIR {cid}", "address": suspect, "chain": "tron",
            "status": "done", "asset": "USDT", "total_sent": mule_amount,
            "graph": {"nodes": nodes, "edges": edges}}


def test_a_synthetic_pair_shares_its_mule_not_its_exchange():
    links = linked([case("c1", A, 900.0), case("c2", B, 400.0)], NONE)
    by = {k["address"]: k for k in links}
    assert HOT not in by                                  # an exchange proves nothing
    mule = by[MULE]
    assert mule["suspects"] == 2 and mule["flags"] == [] and not mule["busy"]
    assert [(r["case_id"], r["hop"], r["amount"]) for r in mule["cases"]] == [
        ("c1", 1, 900.0), ("c2", 1, 400.0)]
    assert by[SCAM]["flags"] == ["on a scam list (Fake exchange)"]
    assert by[HUB]["busy"] is True
    assert links[-1]["address"] == HUB                    # the busy wallet is listed last


def test_one_suspect_traced_twice_is_not_a_link():
    assert linked([case("c1", A, 900.0), case("c1b", A, 900.0)], NONE) == []


def test_a_frozen_shared_wallet_says_so():
    fl = FreezeList({(MULE, "tron"): {"address": MULE, "chain": "tron", "asset": "USDT",
                                      "issuer": "Tether", "frozen_at": "2026-04-02T00:00:00Z",
                                      "tx_hash": "f", "contract": "c"}}, {})
    mule = next(k for k in linked([case("c1", A, 900.0), case("c2", B, 400.0)], fl)
                if k["address"] == MULE)
    assert mule["flags"] == ["Frozen by Tether on 2 Apr 2026"]


def test_a_suspect_reached_by_another_case_links_the_two():
    second = case("c2", B, 400.0)
    second["graph"]["nodes"].append(node(A, 1, "unknown"))
    second["graph"]["edges"].append(edge(B, A, 50.0, "c2x"))
    a = next(k for k in linked([case("c1", A, 900.0), second], NONE) if k["address"] == A)
    assert [(r["case_id"], r["hop"], r["is_suspect"]) for r in a["cases"]] == [
        ("c1", 0, True), ("c2", 1, False)]


def test_related_is_the_links_one_case_is_in():
    cases = [case("c1", A, 900.0), case("c2", B, 400.0), case("c3", "TOther", 1.0)]
    cases[2]["graph"] = {"nodes": [node("TOther", 0, "suspect")], "edges": []}
    assert related("c3", cases, NONE) == []
    assert {k["address"] for k in related("c1", cases, NONE)} == {MULE, HUB, SCAM}
    assert "read a link with its amounts" in LIMIT


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("rec")
    return [run_demo(n, tmp / f"{n}.duckdb") for n in
            ("tron-coindcx", "tron-abstain", "tron-ofac", "tron-terror-link", "tron-htx-coindcx")]


def test_the_recorded_tron_cases_share_one_busy_wallet_and_no_exchange(recorded):
    links = linked(recorded, NONE)
    assert [k["address"] for k in links] == ["TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf"]
    hub = links[0]
    assert hub["busy"] is True and hub["suspects"] == 4
    assert {r["case_id"] for r in hub["cases"]} == {"tron-coindcx", "tron-abstain", "tron-ofac",
                                                   "tron-terror-link"}
    assert all(r["amount"] > 0 and r["hop"] >= 2 for r in hub["cases"])
    # CoinDCX's wallets are reached by two cases and are left out: they are an exchange's
    assert not any(k["label"] == "CoinDCX" for k in links)
