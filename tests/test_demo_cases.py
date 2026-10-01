"""The real demo wallets, end to end, on recorded responses: each attributes as
demo/cases.json expects, and replays identically with no transport at all."""
import json
from datetime import datetime, timezone

import pytest

from demokit import FIX, SPECS, demo_fetcher, demo_provider, run_demo
from vaspfusion.api import schemas as S
from vaspfusion.cases import case_headline
from vaspfusion.chains.base import CacheMiss

EXPECTED = json.loads((FIX / "expected.json").read_text())
COINDCX_2 = "TU7BbAsb8t371eMijQeiGXsiLvY1vZbsFs"          # "CoinDCX 2", Dune spellbook
HTX_POR = "TFTWNgDBkQ5wQoP8RXpRznnHvAVV8x5jLu"            # HTX proof-of-reserves wallet
BITGET_DEP = "0x0008ea70c0ef744f4d8ebe412b9bd875b40c8f24"  # Etherscan tag "Bitget Dep"
OFAC = "TFdHux43bs21qRsygv5WQWfgtbQeT6nXey"                # OFAC SDN list


def by_vasp(case):
    return {(c["vasp"], c["direction"]): c for c in case["candidates"]}


@pytest.mark.parametrize("case_id", list(SPECS))
def test_each_demo_wallet_gives_the_expected_result(case_id, tmp_path):
    case = run_demo(case_id, tmp_path / "cache.duckdb")
    S.CaseDetail.model_validate(case)
    want = SPECS[case_id]["expect"]
    assert (case["outcome"], case["top_vasp"]) == (want["outcome"], want["top_vasp"])
    assert case_headline(case) == EXPECTED[case_id]
    assert case["demo"] is True and case["provenance"]["offline_replay"] is False


@pytest.mark.parametrize("case_id", list(SPECS))
def test_each_demo_wallet_replays_offline_identically(case_id, tmp_path):
    cache = tmp_path / "cache.duckdb"
    live = run_demo(case_id, cache)
    replay = run_demo(case_id, cache, offline=True)       # no transport: cache or nothing
    assert replay["provenance"]["offline_replay"] is True
    for case in (live, replay):
        for key in ("created_at", "provenance"):
            case.pop(key)
    assert replay == live


def test_offline_without_a_cache_refuses_instead_of_guessing(tmp_path):
    with pytest.raises(CacheMiss):
        run_demo("tron-coindcx", tmp_path / "empty.duckdb", offline=True)


def test_where_the_funds_went_always_adds_up(tmp_path):
    for case_id in SPECS:
        case = run_demo(case_id, tmp_path / f"{case_id}.duckdb")
        assert sum(s["share"] for s in case["where_funds_went"]) == pytest.approx(1.0, abs=2e-4)
        assert sum(s["amount"] for s in case["where_funds_went"]) == \
            pytest.approx(case["total_sent"])


# ---- the facts below were read off the chain while choosing the wallets (1 Oct 2026)
def test_tron_wallet_reaches_coindcx_through_a_deposit_address(tmp_path):
    case = run_demo("tron-coindcx", tmp_path / "c.duckdb")
    assert (case["asset"], case["total_sent"]) == ("USDT", 2652.22)
    c = by_vasp(case)[("CoinDCX", "outbound")]
    # the customer's own deposit address, derived in B4 (it sweeps to "CoinDCX 2" with
    # gas from "CoinDCX 10"); before B4 the trace went one hop further, to CoinDCX 2
    assert (c["hops"], c["share_of_funds"], c["label_tier"]) == (1, 0.5769, "derived")
    assert c["deposit_address"] == "TCw8j3nQFnRDMUW2SeNbAgjnVKpELLcoV5"
    assert c["path"] == ["TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c",
                         "TCw8j3nQFnRDMUW2SeNbAgjnVKpELLcoV5"]
    # B6: the model confirms this deposit address, so the label carries 0.85 (the weight of
    # the curated CoinDCX wallet it sweeps to) x the model's probability, with its range;
    # the rules' own confidence was 0.8075
    assert c["confidence"] == 0.8491 and c["confidence_interval"] == [0.8491, 0.85]
    assert [e["kind"] for e in c["evidence"]] == ["label", "model", "model", "model", "model",
                                                  "path"]
    assert c["evidence"][1]["text"].startswith("Deposit-address model: over 0.99 that an "
                                               "address behaving like TCw8j3…LLcoV5")
    assert "Sweep rule: forwarded 100% of the 847,730 USDT it received from 2 senders to " \
           "CoinDCX wallet TU7BbA…vZbsFs" in c["evidence"][0]["text"]
    assert "Both rules agree." in c["evidence"][0]["text"]
    assert [h["tx_hash"][:10] for h in case["hop_rail"]] == ["54baf9710b"]
    assert [(s["kind"], s["name"], s["share"]) for s in case["where_funds_went"]] == \
        [("vasp", "CoinDCX", 0.5769), ("hub", None, 0.4231)]
    hub = next(n for n in case["graph"]["nodes"] if n["role"] == "hub")
    assert hub["id"] == "TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf"
    assert "CoinDCX" in case["next_steps"][0]


def test_eth_wallet_reaches_a_tagged_bitget_deposit_and_spoofs_are_ignored(tmp_path):
    case = run_demo("eth-bitget", tmp_path / "c.duckdb")
    assert (case["asset"], case["total_sent"]) == ("USDT", 552163.80319)
    c = by_vasp(case)[("Bitget", "outbound")]
    assert (c["hops"], c["share_of_funds"], c["label_tier"], c["confidence"]) == \
        (1, 1.0, "explorer_tag", 0.75)
    assert c["deposit_address"] == BITGET_DEP
    nodes = {n["id"]: n for n in case["graph"]["nodes"]}
    assert nodes[BITGET_DEP]["role"] == "exchange_deposit"
    # the wallet's history is full of fake-token transfers to look-alike addresses
    assert not any(a.startswith("0x0001d9") or a.startswith("0x000e42") for a in nodes)
    assert all(e["asset"] == "USDT" for e in case["graph"]["edges"])
    assert "Not followed in this run" in case["narrative"] and "ETH" in case["narrative"]


def test_tron_wallet_that_paid_an_ofac_listed_address(tmp_path):
    case = run_demo("tron-ofac", tmp_path / "c.duckdb")
    flag = case["typology_flags"][0]
    assert (flag["code"], flag["severity"], flag["wallet"]) == ("sanctioned_contact", "high", OFAC)
    assert flag["figures"]["share"] == pytest.approx(0.9894, abs=1e-4)
    assert flag["figures"]["amount"] == 100008.0
    assert case["where_funds_went"][0] == {"kind": "sanctioned", "name": "OFAC SDN",
                                           "share": 0.9894, "amount": 100008.0}
    assert case["hop_rail"][-1]["to_address"] == OFAC
    assert "No labelled exchange was reached." in case["narrative"]
    assert case["next_steps"][0].startswith("Escalate")


def test_tron_wallet_split_between_two_exchanges_names_both(tmp_path):
    case = run_demo("tron-htx-coindcx", tmp_path / "c.duckdb")
    assert case["total_sent"] == 13000.0
    out = [c for c in case["candidates"] if c["direction"] == "outbound"]
    assert [(c["vasp"], c["proximity_rank"], c["hops"], c["share_of_funds"]) for c in out] == \
        [("CoinDCX", 1, 1, 0.4615), ("HTX", 2, 2, 0.5385)]
    # CoinDCX is nearer since B4: its deposit address is a derived label one hop away
    assert out[0]["deposit_address"] == "TLUQsVHsmUrcWEy3tGrpEdh2ue8z2NHPYk"
    assert out[0]["label_tier"] == "derived" and out[1]["deposit_address"] == HTX_POR
    assert case["top_vasp"] == "CoinDCX"
    assert all(c["confidence"] >= 0.60 for c in out)
    assert {s["kind"] for s in case["where_funds_went"]} == {"vasp"}     # every unit accounted
    assert sum("Draft a request" in s for s in case["next_steps"]) == 2
    # 1,200 USDT took 2 hops to HTX and 5,800 took 3
    assert "7,000 USDT (54%) reached HTX in 2 to 3 hops" in case["narrative"]
    assert "6,000 USDT (46%) reached CoinDCX in 1 hop" in case["narrative"]


def test_tron_wallet_with_a_weak_lead_abstains(tmp_path):
    case = run_demo("tron-abstain", tmp_path / "c.duckdb")
    assert (case["top_vasp"], case["confidence"]) == (None, None)
    lead = case["candidates"][0]
    assert lead["vasp"] == "CoinDCX" and lead["confidence"] < 0.60
    assert "CoinDCX" in case["abstain_reason"] and "0.60" in case["abstain_reason"]
    assert case["what_would_change"]
    assert "No exchange is named." in case["narrative"]


def test_eth_wallet_whose_money_never_reached_a_label_abstains(tmp_path):
    case = run_demo("eth-abstain", tmp_path / "c.duckdb")
    assert [c for c in case["candidates"] if c["direction"] == "outbound"] == []
    # 10,000 USDT went into two wallets that each took 500+ incoming transfers in the next
    # few days: the page cap is reached before any outflow could be seen, so "still there"
    # is not claimed for them. The other 12,214.70 sits in a wallet whose listing is whole.
    kinds = {s["kind"]: s["amount"] for s in case["where_funds_went"]}
    assert kinds == {"not_moved": 12214.697568, "not_followed": 10000.0}
    assert "more transfers than one fetch reads" in case["abstain_reason"]
    assert any("0x6f48" in w and "full history" in w for w in case["what_would_change"])


# ---- adapters say whether a listing is the whole answer
def test_a_listing_read_to_its_end_is_complete(tmp_path):
    tron = demo_provider("tron", demo_fetcher(tmp_path / "t.duckdb", "tron-coindcx"))
    swept = tron.transfers("TCw8j3nQFnRDMUW2SeNbAgjnVKpELLcoV5", "out", limit=100, asset="USDT",
                           since=datetime(2025, 5, 25, 3, 22, 15, tzinfo=timezone.utc))
    assert len(swept) >= 1 and swept.complete is True
    eth = demo_provider("ethereum", demo_fetcher(tmp_path / "e.duckdb", "eth-bitget"))
    sent = eth.transfers(SPECS["eth-bitget"]["address"], "out", limit=100, asset="USDT")
    assert len(sent) >= 2 and sent.complete is True


def test_a_listing_cut_by_the_limit_is_not_complete(tmp_path):
    tron = demo_provider("tron", demo_fetcher(tmp_path / "t.duckdb", "tron-coindcx"))
    hub = tron.transfers("TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf", "out", limit=100, asset="USDT",
                         since=datetime(2025, 7, 14, 16, 12, 48, tzinfo=timezone.utc))
    assert len(hub) == 100 and hub.complete is False
