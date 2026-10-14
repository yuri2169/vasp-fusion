"""Freeze marks on a served case: which of its wallets Tether has frozen, and where they
sit (the wallet itself, the Hop Rail's path, elsewhere in the graph)."""
from vaspfusion.freezes import case_freezes
from vaspfusion.labels.frozen import FreezeList

S = "TSuspectAAAAAAAAAAAAAAAAAAAAAAAAAA"
M = "TMiddleBBBBBBBBBBBBBBBBBBBBBBBBBBB"
X = "TExchangeCCCCCCCCCCCCCCCCCCCCCCCCC"
F = "TFunderDDDDDDDDDDDDDDDDDDDDDDDDDDD"
E = "0x1111111111111111111111111111111111111111"


def fl(*addrs, chain="tron", at="2024-08-03T10:00:00Z"):
    return FreezeList({(a, chain): {"address": a, "chain": chain, "asset": "USDT",
                                    "issuer": "Tether", "frozen_at": at, "tx_hash": "0xf",
                                    "contract": "c"} for a in addrs}, {})


def case():
    return {"id": "c1", "address": S, "chain": "tron", "asset": "USDT",
            "hop_rail": [{"from_address": S, "to_address": M, "tx_hash": "0x0"},
                         {"from_address": M, "to_address": X, "tx_hash": "0x1"}],
            "graph": {"nodes": [
                {"id": S, "address": S, "chain": "tron", "role": "suspect", "hop": 0},
                {"id": M, "address": M, "chain": "tron", "role": "intermediary", "hop": 1},
                {"id": X, "address": X, "chain": "tron", "role": "exchange", "hop": 2},
                {"id": F, "address": F, "chain": "tron", "role": "unknown", "hop": 1},
                {"id": "ethereum:" + E, "address": E, "chain": "ethereum", "role": "unknown",
                 "hop": 3}],
                "edges": [
                    {"source": S, "target": M, "traced_amount": 900.0, "direction": "outbound",
                     "asset": "USDT"},
                    {"source": M, "target": X, "traced_amount": 850.5, "direction": "outbound",
                     "asset": "USDT"},
                    {"source": F, "target": S, "traced_amount": 40.0, "direction": "inbound",
                     "asset": "USDT"}]}}


def test_nothing_frozen_is_an_empty_list():
    assert case_freezes(case(), fl()) == []


def test_marks_say_where_each_frozen_wallet_sits_and_what_reached_it():
    marks = case_freezes(case(), fl(S, M, F))
    assert [(m["address"], m["where"], m["side"], m["hop"]) for m in marks] == [
        (S, "origin", "origin", 0), (M, "path", "outbound", 1), (F, "graph", "inbound", 1)]
    m = marks[1]
    assert m["amount"] == 900.0 and m["asset"] == "USDT"
    assert m["text"] == "Frozen by Tether on 3 Aug 2024"
    assert m["issuer"] == "Tether" and m["frozen_at"] == "2024-08-03T10:00:00Z"
    assert marks[2]["amount"] == 40.0          # a funder: what it sent the wallet


def test_a_wallet_on_another_chain_is_looked_up_on_its_own_chain():
    marks = case_freezes(case(), fl(E, chain="ethereum"))
    assert [(m["address"], m["chain"]) for m in marks] == [(E, "ethereum")]
    assert marks[0]["amount"] == 0.0


def test_a_case_without_a_graph_still_screens_its_own_wallet():
    bare = {"id": "c2", "address": S, "chain": "tron", "hop_rail": [], "graph": None}
    assert [m["where"] for m in case_freezes(bare, fl(S))] == ["origin"]


# ------------------------------------------------------------------ in the risk score
from vaspfusion import risk as R  # noqa: E402


def done(c):
    return {**c, "status": "done", "outcome": "INSUFFICIENT_EVIDENCE", "candidates": [],
            "typology_flags": [], "where_funds_went": [], "total_sent": 1000.0,
            "total_received": 40.0,
            "graph": {**c["graph"], "edges": [{**e, "id": f"e{i}", "tx_hash": f"0x{i}"}
                                              for i, e in enumerate(c["graph"]["edges"])]}}


def test_a_frozen_wallet_on_the_path_is_an_indicator_with_its_transfer():
    c = done(case())
    c["freezes"] = case_freezes(c, fl(M))
    risk = R.case_risk(c)
    ind = {i["code"]: i for i in risk["indicators"]}
    assert set(ind) == {"frozen_contact"}
    assert ind["frozen_contact"]["points"] == 35 + round(10 * 0.9)
    assert ind["frozen_contact"]["tx_hashes"] == ["0x0"]
    assert "was frozen by Tether on 3 Aug 2024 (USDT)" in ind["frozen_contact"]["text"]
    assert risk["risk_class"] == "medium"
    assert risk["flows"][0]["tx_hash"] == "0x0"


def test_the_wallet_itself_and_its_funder():
    c = done(case())
    c["freezes"] = case_freezes(c, fl(S, F))
    codes = {i["code"]: i["points"] for i in R.case_risk(c)["indicators"]}
    assert codes == {"frozen_self": 60, "frozen_funding": 25 + 10}


def test_no_freezes_given_means_none_counted():
    c = done(case())
    c["freezes"] = []
    assert R.case_risk(c)["indicators"] == []


def test_the_wallet_page_counts_its_own_freeze():
    row = {"address": S, "chain": "tron", "asset": "USDT", "issuer": "Tether",
           "frozen_at": "2025-11-04T08:00:00Z", "tx_hash": "0xf", "contract": "c"}
    risk = R.wallet_risk(S, None, [], freeze=row)
    assert [i["code"] for i in risk["indicators"]] == ["frozen_self"]
    assert risk["risk_class"] == "high"
    assert "was frozen by Tether on 4 Nov 2025 (USDT)" in risk["reasons"][0]
    assert R.wallet_risk(S, None, [])["risk_class"] is None
