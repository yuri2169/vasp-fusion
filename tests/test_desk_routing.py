"""Cases to desk: which wallets route to which exchange, on the real demo wallets."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deskkit import demo_case, demo_cases  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402
from vaspfusion.desk.directory import Directory  # noqa: E402
from vaspfusion.desk.routing import build_desk, routed_wallets, vasp_detail  # noqa: E402

TODAY = date(2026, 10, 2)


def _req(rid, vasp, status, wallets, due=None, created="2026-10-02T09:30:00Z"):
    return {"id": rid, "reference": rid.upper(), "vasp": vasp, "status": status,
            "case_ids": sorted({w[0] for w in wallets}), "created_at": created, "due": due,
            "letter": {"wallets": [{"case_id": c, "address": a} for c, a in wallets]}}


def test_a_split_wallet_routes_to_both_exchanges_with_exact_amounts():
    coindcx, htx = routed_wallets(demo_case("tron-htx-coindcx"))
    assert (coindcx["vasp"], coindcx["address"], coindcx["tier"]) == (
        "CoinDCX", "TLUQsVHsmUrcWEy3tGrpEdh2ue8z2NHPYk", "derived")
    assert (coindcx["amount"], coindcx["amount_usd"], coindcx["asset"]) == (6000.0, 6000.0, "USDT")
    assert coindcx["paid_into"] is None and coindcx["case_ref"] == "DEMO/2026/104"
    assert (coindcx["kind"], coindcx["label"]) == (
        "deposit", "CoinDCX deposit address (derived: sweep + gas payer)")
    assert coindcx["reached_at"] == "2024-07-23T08:44:12Z"
    assert coindcx["tx_hashes"] == [
        "a12af76b0c4c89cdc0a316d9dc7f23a72b48844f197c0944effb684461f80dae"]
    # HTX: the account is the wallet that passed everything on to HTX's published wallet
    assert (htx["vasp"], htx["address"], htx["paid_into"], htx["tier"]) == (
        "HTX", "THW7GJwxsZgZMdVrKTn2brDnNXXguUJt6a", "TFTWNgDBkQ5wQoP8RXpRznnHvAVV8x5jLu",
        "published_por")
    assert htx["amount"] == 7000.0 and htx["counterfactual_holds"] is False
    assert len(htx["tx_hashes"]) >= 2


def test_the_account_follows_the_same_rule_as_the_case_next_step():
    for cid in ("tron-coindcx", "tron-htx-coindcx", "eth-bitget"):
        case = demo_case(cid)
        for w in routed_wallets(case):
            step = next(s for s in case["next_steps"] if s.startswith(f"Draft a request to {w['vasp']}"))
            assert f"{w['address'][:6]}…{w['address'][-6:]}" in step


def test_cases_that_name_no_exchange_route_nothing():
    for cid in ("tron-abstain", "tron-ofac", "eth-bridge"):
        assert routed_wallets(demo_case(cid)) == [], cid


def test_a_candidate_under_the_bar_or_inbound_or_unroutable_is_never_routed():
    case = demo_case("tron-coindcx")
    c = case["candidates"][0]
    for change in ({"confidence": 0.59}, {"direction": "inbound"},
                   {"vasp": "Unidentified exchange"}):
        assert routed_wallets({**case, "candidates": [{**c, **change}]}) == []
    assert routed_wallets({**case, "status": "running"}) == []


def test_a_case_stored_before_b8_is_not_routed_until_traced_again():
    case = demo_case("tron-htx-coindcx")
    old = {**case, "candidates": [{k: v for k, v in c.items()
                                   if k not in ("amount", "request_wallets")}
                                  for c in case["candidates"]]}
    assert routed_wallets(old) == []
    page = vasp_detail("CoinDCX", Directory.load(), {}, [old], [])
    assert [(w["routable"], w["address"]) for w in page["wallets"]] == [
        (False, "TLUQsVHsmUrcWEy3tGrpEdh2ue8z2NHPYk")]


def test_the_exchanges_own_wallet_is_not_a_letter():
    case = demo_case("tron-coindcx")
    c = {**case["candidates"][0], "hops": 0, "request_wallets": []}
    assert routed_wallets({**case, "candidates": [c]}) == []


def test_what_an_exchange_sent_the_wallet_has_no_dollar_figure():
    case = demo_case("tron-coindcx")
    inbound = {**case["candidates"][0], "direction": "inbound", "amount": 5000.0,
               "request_wallets": []}
    page = vasp_detail("CoinDCX", Directory.load(), {}, [{**case, "candidates": [inbound]}], [])
    assert [(w["direction"], w["amount_usd"], w["routable"]) for w in page["wallets"]] == [
        ("inbound", None, False)]


def test_the_rows_of_an_exchange_add_up_to_what_reached_it():
    for cid in ("tron-coindcx", "tron-htx-coindcx", "eth-bitget"):
        case = demo_case(cid)
        routed = routed_wallets(case)
        for c in case["candidates"]:
            mine = [w["amount"] for w in routed if w["vasp"] == c["vasp"]]
            if mine:
                assert abs(sum(mine) - c["amount"]) < 1e-9, (cid, c["vasp"])


def test_a_withdrawn_request_counts_for_nothing_on_the_desk():
    cases = demo_cases("eth-bitget")
    w = routed_wallets(cases[0])[0]
    reqs = [_req("req-2026-0001", "Bitget", "withdrawn", [("eth-bitget", w["address"])])]
    row = build_desk(cases, reqs, TODAY)["rows"][0]
    assert (row["status"], row["unrequested_wallets"], row["last_request_id"]) == (
        "not_requested", 1, None)
    assert build_desk([], reqs, TODAY)["rows"] == []


def test_the_desk_has_one_row_per_exchange_across_cases():
    desk = build_desk(demo_cases(), [], TODAY)
    S.Desk.model_validate(desk)
    rows = {r["vasp"]: r for r in desk["rows"]}
    assert set(rows) == {"CoinDCX", "HTX", "Bitget"}
    assert rows["CoinDCX"]["case_ids"] == ["tron-coindcx", "tron-htx-coindcx"]
    assert rows["CoinDCX"]["wallet_count"] == 2 and rows["CoinDCX"]["unrequested_wallets"] == 2
    assert rows["CoinDCX"]["total_usd"] == 7530.0           # 1,530 + 6,000 USDT, exact
    assert rows["Bitget"]["total_usd"] == 552163.8
    for r in rows.values():
        assert (r["status"], r["next_action"], r["last_request_id"]) == (
            "not_requested", "Draft request", None)
    assert [r["vasp"] for r in desk["rows"]] == ["Bitget", "CoinDCX", "HTX"]   # largest first
    assert desk["follow_ups"] == []


def test_a_row_follows_its_latest_request_and_counts_what_is_not_yet_requested():
    cases = demo_cases("tron-coindcx", "tron-htx-coindcx")
    first = routed_wallets(cases[0])[0]
    reqs = [_req("req-2026-0001", "CoinDCX", "sent", [("tron-coindcx", first["address"])],
                 due="2026-10-09")]
    row = next(r for r in build_desk(cases, reqs, TODAY)["rows"] if r["vasp"] == "CoinDCX")
    assert (row["status"], row["last_request_id"], row["unrequested_wallets"]) == (
        "sent", "req-2026-0001", 1)
    assert row["next_action"] == "Draft a request for 1 wallet not yet requested"
    both = reqs + [_req("req-2026-0002", "CoinDCX", "drafted",
                        [("tron-htx-coindcx", "TLUQsVHsmUrcWEy3tGrpEdh2ue8z2NHPYk")],
                        created="2026-10-02T10:00:00Z")]
    row = next(r for r in build_desk(cases, both, TODAY)["rows"] if r["vasp"] == "CoinDCX")
    assert (row["status"], row["last_request_id"], row["unrequested_wallets"]) == (
        "drafted", "req-2026-0002", 0)
    assert row["next_action"] == "Review and approve the draft"


def test_a_refused_request_still_counts_as_requested():
    cases = demo_cases("eth-bitget")
    w = routed_wallets(cases[0])[0]
    reqs = [_req("req-2026-0001", "Bitget", "refused", [("eth-bitget", w["address"])])]
    row = build_desk(cases, reqs, TODAY)["rows"][0]
    assert row["status"] == "refused" and row["unrequested_wallets"] == 0
    assert row["next_action"].startswith("Refused")


def test_a_reply_is_overdue_the_day_after_it_was_due():
    cases = demo_cases("eth-bitget")
    w = routed_wallets(cases[0])[0]
    reqs = [_req("req-2026-0001", "Bitget", "sent", [("eth-bitget", w["address"])],
                 due="2026-10-09")]
    assert build_desk(cases, reqs, date(2026, 10, 9))["follow_ups"] == []
    desk = build_desk(cases, reqs, date(2026, 10, 10))
    assert desk["follow_ups"] == [{
        "kind": "reply_overdue", "vasp": "Bitget", "request_id": "req-2026-0001",
        "due": "2026-10-09", "text": "Bitget has not replied; the reply was due 9 Oct 2026"}]
    assert desk["rows"][0]["next_action"] == "Follow up: the reply was due 9 Oct 2026"
    answered = [{**reqs[0], "status": "answered"}]
    assert build_desk(cases, answered, date(2026, 10, 10))["follow_ups"] == []


def test_a_request_keeps_its_row_when_its_case_is_gone():
    reqs = [_req("req-2026-0001", "OKX", "sent", [("gone", "Taddr")], due="2026-10-09")]
    row = build_desk([], reqs, TODAY)["rows"][0]
    assert (row["vasp"], row["wallet_count"], row["case_ids"], row["status"]) == (
        "OKX", 1, ["gone"], "sent")


def test_the_vasp_page_lists_every_case_wallet_and_request():
    cases = demo_cases()
    reqs = [_req("req-2026-0001", "CoinDCX", "drafted",
                 [("tron-coindcx", "TCw8j3LLcoV5")])]
    page = vasp_detail("coindcx", Directory.load(), {"tron": 571}, cases, reqs)
    S.VaspDetail.model_validate(page)
    assert page["directory"]["legal_name"] == "Neblio Technologies Private Limited"
    assert page["label_counts"] == {"tron": 571}
    by_case = {w["case_id"]: w for w in page["wallets"]}
    assert set(by_case) == {"tron-coindcx", "tron-htx-coindcx", "tron-abstain"}
    assert by_case["tron-abstain"]["confidence"] < 0.6          # shown, though not routed
    assert by_case["tron-htx-coindcx"]["amount_usd"] == 6000.0
    assert [r["id"] for r in page["requests"]] == ["req-2026-0001"]
