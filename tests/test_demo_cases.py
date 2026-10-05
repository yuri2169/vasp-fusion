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
                                                  "path", "counterfactual"]
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


# ---- B7: flags, counterfactual and leads on the real wallets
def flags_of(case, code):
    return [f for f in case["typology_flags"] if f["code"] == code]


def test_the_named_exchange_survives_without_the_deposit_address_label(tmp_path):
    case = run_demo("tron-coindcx", tmp_path / "c.duckdb")
    c = by_vasp(case)[("CoinDCX", "outbound")]
    # hide the derived label: the deposit address is followed one hop on, into "CoinDCX 2"
    assert c["counterfactual_holds"] is True and c["counterfactual"] == (
        "Still CoinDCX without the label on TCw8j3…LLcoV5: 58% of the funds reach CoinDCX at "
        "TU7BbA…vZbsFs (curated list) in 2 hops, confidence 0.72 (was 0.85).")
    assert c["evidence"][-1]["weight"] == pytest.approx(0.7225 - 0.8491)
    assert "Checked without its strongest evidence: Still CoinDCX" in case["narrative"]
    bitget = by_vasp(run_demo("eth-bitget", tmp_path / "e.duckdb"))[("Bitget", "outbound")]
    assert bitget["counterfactual_holds"] is True          # swept on to "Bitget 6"
    assert "at 0x1ab4…8f8f23 (explorer tag) in 2 hops, confidence 0.64" in bitget["counterfactual"]


def test_an_answer_resting_on_one_label_is_reported_as_such(tmp_path):
    case = run_demo("tron-htx-coindcx", tmp_path / "c.duckdb")
    htx = by_vasp(case)[("HTX", "outbound")]
    assert htx["counterfactual_holds"] is False
    assert htx["counterfactual"] == ("Without the label on TFTWNg…8x5jLu, HTX is not reached at "
                                     "all: naming HTX rests on that one label.")
    assert by_vasp(case)[("CoinDCX", "outbound")]["counterfactual_holds"] is True
    assert case["top_vasp"] == "CoinDCX" and case["outcome"] == "ATTRIBUTED"    # unchanged


def test_the_other_half_of_the_hero_wallets_money_is_a_lead_not_an_answer(tmp_path):
    case = run_demo("tron-coindcx", tmp_path / "c.duckdb")
    lead, = flags_of(case, "deposit_like")
    # 42% went to an unlabelled wallet that sweeps everything into the busy unlabelled
    # wallet TDqSqu…: the model reads that as deposit-address behaviour, and says no more
    assert lead["wallet"] == "TDYCQEb133CBz8mGDpkBXh9TcafSyPdsUJ" and lead["severity"] == "info"
    assert lead["figures"]["share"] == 0.4231 and lead["figures"]["p"] >= 0.99
    assert "behaves like an exchange deposit address" in lead["text"]
    assert "Neither it nor TDqSqu…dkhSCf, the wallet it sweeps into, is labelled" in lead["text"]
    assert "A lead to check, not a finding" in lead["text"] and "over 0.99" in lead["text"]
    # the lead added no exchange to where the money went ...
    assert [c["vasp"] for c in case["candidates"] if c["direction"] == "outbound"] == ["CoinDCX"]
    # ... (the wallet's own funding is another matter: 14 USDT came from a Binance wallet
    # that the GraphSense TagPacks name, B5)
    funders = [(c["vasp"], c["label_tier"], round(c["share_of_funds"], 3))
               for c in case["candidates"] if c["direction"] == "inbound"]
    assert funders == [("Binance", "curated", 0.005)]
    assert case["next_steps"][0].startswith("Draft a request to CoinDCX")
    assert case["next_steps"][-1].startswith("Identify TDqSqu…dkhSCf")
    assert "Lead, not a finding: TDYCQE…yPdsUJ behaves like" in case["narrative"]
    assert case["provenance"]["notes"] == ["Deposit-address model: 1 unlabelled wallet on the "
                                           "trail scored, 1 behaves like a deposit address."]


def test_leads_do_not_turn_an_abstain_into_an_answer(tmp_path):
    case = run_demo("tron-abstain", tmp_path / "c.duckdb")
    leads = flags_of(case, "deposit_like")
    assert [f["wallet"][:6] for f in leads] == ["TMPJaN", "TLfVvt"]
    assert case["outcome"] == "INSUFFICIENT_EVIDENCE" and case["top_vasp"] is None
    assert case["what_would_change"][0].startswith("A label for TWBPGL…yJW1JJ, the wallet "
                                                   "TMPJaN…YyzeAJ sweeps into")
    assert case["next_steps"][0].startswith("Identify TWBPGL…yJW1JJ")
    assert case["candidates"][0]["counterfactual"] is None       # not named, so not checked
    assert "5 unlabelled wallets on the trail scored, 2 behave" in case["provenance"]["notes"][0]


def test_a_lead_that_pays_a_labelled_exchange_wallet_names_it_as_a_question(tmp_path):
    case = run_demo("tron-htx-coindcx", tmp_path / "c.duckdb")
    lead, = flags_of(case, "deposit_like")
    assert lead["wallet"].startswith("THW7GJ")
    assert "is labelled HTX (published by the exchange itself), so it may be a deposit " \
           "address of HTX that the discovery rules have not derived" in lead["text"]


def test_real_flags_carry_figures_and_hashes_from_the_trace(tmp_path):
    case = run_demo("tron-abstain", tmp_path / "c.duckdb")
    hashes = {e["tx_hash"] for e in case["graph"]["edges"]}
    assert [f["code"] for f in case["typology_flags"]] == \
        ["rapid_forwarding"] * 5 + ["fan_in", "deposit_like", "deposit_like"]
    for f in case["typology_flags"]:
        assert f["tx_hashes"] and set(f["tx_hashes"]) <= hashes and f["figures"]
    rapid = case["typology_flags"][0]
    assert rapid["figures"] == {"share": 1.0, "amount": 395.0, "seconds": 141.0}
    merge, = flags_of(case, "fan_in")
    assert merge["wallet"] == "TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf"
    assert merge["figures"] == {"senders": 3.0, "amount": 721.0}
    split = run_demo("tron-htx-coindcx", tmp_path / "s.duckdb")
    assert flags_of(split, "round_amounts")[0]["figures"] == \
        {"round_transfers": 3.0, "transfers": 3.0, "amount": 13000.0}


def test_ethereum_wallets_are_not_scored_and_the_case_says_why(tmp_path):
    case = run_demo("eth-abstain", tmp_path / "c.duckdb")
    assert flags_of(case, "deposit_like") == []
    assert case["provenance"]["notes"] == [
        "4 unlabelled wallets on the trail not scored by the deposit-address model: it is only "
        "used on Tron, where it recognised the deposit addresses of an exchange it had never "
        "seen."]


def test_eth_wallet_whose_money_went_into_a_bridge_is_followed_onto_base(tmp_path):
    """Real: 0x2102…f364b0 put 8,250 USDT into Across in two deposits. Across' index names
    Base and the same address as recipient; the payouts are read on Base, and the trace
    goes on there. No exchange is reached within 3 hops, and the case says so."""
    case = run_demo("eth-bridge", tmp_path / "c.duckdb")
    across = "0x5c7bcd6e7de5423a257d81b442095a1a6ced35c5"     # "Across Protocol: Ethereum Spoke Pool V2"
    me = SPECS["eth-bridge"]["address"]
    assert case["outcome"] == "INSUFFICIENT_EVIDENCE" and case["candidates"] == []
    assert case["chains"] == ["ethereum", "base"]
    small, big = [x for x in case["crossings"] if x["bridge"] == "Across Protocol"]
    assert (big["status"], big["dest_chain"], big["recipient"], big["matched_by"]) == \
        ("followed", "base", me, "app.across.to")
    # what arrived is read on Base: less than the 7,796.877993 Across' index quotes
    assert (big["amount_in"], big["asset_out"], big["amount_out"], big["seconds"]) == \
        (7800.0, "USDC", 7777.385799, 54)
    assert (small["amount_in"], small["amount_out"], small["seconds"]) == (450.0, 448.693209, 8)
    assert round(big["fee"] + small["fee"], 6) == 23.920992
    # the fee is a fee, nothing is left "at the bridge", and the slices still add up
    where = {(w["kind"], w["name"]): w["amount"] for w in case["where_funds_went"]}
    assert ("bridge", "Across Protocol") not in where
    assert where[("bridge_fee", None)] == 23.920992
    assert round(sum(where.values()), 4) == case["total_sent"]
    # the same address is two wallets: the suspect on Ethereum, the recipient on Base
    nodes = {n["id"]: n for n in case["graph"]["nodes"]}
    assert (nodes[me]["chain"], nodes[me]["role"]) == ("ethereum", "suspect")
    assert (nodes[f"base:{me}"]["chain"], nodes[f"base:{me}"]["address"],
            nodes[f"base:{me}"]["hop"]) == ("base", me, 2)
    assert nodes[across]["role"] == "bridge" and nodes[across]["cluster"] is None
    edge = next(e for e in case["graph"]["edges"] if e["tx_hash"] == big["payout_tx"])
    assert (edge["source"], edge["target"], edge["chain"], edge["bridge"]["source_tx"]) == \
        (across, f"base:{me}", "base", big["source_tx"])
    # the rail crosses: deposit on Ethereum, payout on Base, then on from the recipient
    rail = case["hop_rail"]
    assert [(h["from_chain"], h["to_chain"], h["bridge"] is not None) for h in rail] == [
        ("ethereum", "ethereum", False), ("ethereum", "base", True), ("base", "base", False)]
    assert (rail[1]["from_address"], rail[1]["to_address"], rail[1]["tx_hash"]) == \
        (across, me, big["payout_tx"])
    assert case["tx_chains"][big["payout_tx"]] == "base" and big["source_tx"] not in case["tx_chains"]
    first, second = flags_of(case, "bridge_hop")
    assert (first["wallet"], first["severity"], first["figures"]["hops"]) == (across, "warn", 1.0)
    assert first["text"].endswith("(Across Protocol), 1 hop away; followed onto Base")
    assert "60% crossed to Base through the Across Protocol bridge and was followed there" \
        in case["abstain_reason"]
    assert "8,226.08 USDC of it arrived at 0x2102…f364b0 on Base" in case["narrative"]
    assert "Tracing deeper than 3 hops from 0xd888…1008a9 on Base (42% of the funds)" \
        in case["what_would_change"]
    # a bridge with no resolver stays as before: the officer is told what to follow by hand
    assert second["figures"]["amount"] == 500.0 and "followed onto" not in second["text"]
    assert case["what_would_change"][0] == ("Following the funds across the bridge (Optimism) "
                                            "onto the destination chain")
    assert case["next_steps"][0].startswith(
        "Follow the 500 USDT that went into the Optimism bridge at 0x99c9…884be1 onto the "
        "destination chain: a bridge is not an exchange")
    assert not any(s.startswith("Draft a request") for s in case["next_steps"])
    assert not any("Across" in s for s in case["next_steps"])
    assert "app.across.to" in case["provenance"]["data_sources"]
    assert "base.blockscout.com" in case["provenance"]["data_sources"]


def test_the_bridged_case_replays_offline_with_the_same_fingerprint(tmp_path):
    live = run_demo("eth-bridge", tmp_path / "c.duckdb")
    again = run_demo("eth-bridge", tmp_path / "c.duckdb", offline=True)
    assert again["provenance"]["findings_sha256"] == live["provenance"]["findings_sha256"]
    assert again["provenance"]["offline_replay"] is True and again["chains"] == live["chains"]


def test_no_wallet_id_leaks_into_what_an_officer_reads(tmp_path):
    """`chain:address` is an id for the graph only. Every sentence and every address
    field carries the plain address (and says the chain in words)."""
    case = run_demo("eth-bridge", tmp_path / "c.duckdb")
    ids = {"source", "target", "id", "wallet_ids"}

    def walk(v, key=None):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, str) and key not in ids:
            assert "base:0x" not in v and "ethereum:0x" not in v, (key, v)
    walk(case)


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
