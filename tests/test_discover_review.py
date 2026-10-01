"""Defects found by the code review of B4, each pinned by a test."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from test_discover_crawl import LABELS as CRAWL_LABELS, Chain, Labels, deposit_and_sweep, ev
from test_discover_rules import A, CFG, LABELS, gas, gas_ev, swept
from tracekit import CHAIN, T0, ToyLabels, tx
from vaspfusion.chains.base import GasEvent, GasList
from vaspfusion.discover.crawl import CrawlConfig, DiscoveryResult, discover
from vaspfusion.discover.rules import decide, evidence_text, sweep_rule
from vaspfusion.discover.store import write_result
from vaspfusion.labels.load import build_labels
from vaspfusion.labels.lookup import LabelStore


def run(transfers, gas_events=None, labels=CRAWL_LABELS, **cfg):
    chain = Chain(transfers, gas_events)
    cfg.setdefault("window_start", T0)
    return discover(CHAIN, chain, chain, Labels(labels), CrawlConfig(**cfg))


def by_address(result):
    return {f.address: f for f in result.findings}


# ------------------------------------------------- 1. a payer with a non-exchange label
def test_a_sanctioned_gas_payer_is_named_with_its_label_not_called_unlabelled():
    g = gas([gas_ev("OFAC", 29)])
    assert g.verdict == "other_label" and g.payer == "OFAC"
    assert g.other_labels == {"OFAC": "Lazarus (sanctioned)"}
    text = evidence_text(swept(), g, decide(swept(), g.verdict, existing=None))
    assert "Gas rule: OFAC, labelled Lazarus (sanctioned), paid the energy for 1 of 2 sweeps." \
        in text
    assert "Sweep rule only." in text


def test_a_payer_with_any_label_never_becomes_a_gas_station():
    rows, gas_events = [], {}
    for i in range(12):
        rows += deposit_and_sweep(10 * i + 1, f"D{i:02d}", "HOT", i)
        gas_events[f"D{i:02d}"] = [ev("BAD", i + 4)]
    result = run(rows, gas_events)
    assert result.stations == []
    assert {f.rule for f in result.findings} == {"sweep"}
    assert all("labelled Lazarus (sanctioned)" in f.evidence for f in result.findings)


# ------------------------------------------------- 2. disagreement between runs
def test_an_earlier_derived_label_for_another_exchange_is_a_conflict():
    earlier = ToyLabels({A: ("ExB", "exchange", "deposit", "derived")}).labels[A]
    d = decide(swept(), "confirmed", existing=earlier)
    assert d.status == "conflict"
    assert d.conflict == "an earlier run derived it as a ExB deposit address"
    same = ToyLabels({A: ("ExA", "exchange", "deposit", "derived")}).labels[A]
    assert decide(swept(), "confirmed", existing=same).status == "derived"


FIX = __import__("pathlib").Path(__file__).parent / "fixtures" / "labels"
REAL_DEP = "TTTZH6nWX8tk1b73xHfCJk3x9aBRgWbeEK"


def finding(result_of, **changes):
    base = by_address(result_of)["D1"]
    return replace(base, chain="tron", **changes)


@pytest.fixture
def one():
    return run(deposit_and_sweep(1, "D1", "HOT", 0))


def test_two_runs_naming_different_exchanges_for_one_address_load_neither(tmp_path, one):
    a = finding(one, address=REAL_DEP, entity="CoinDCX", confidence=0.68)
    b = finding(one, address=REAL_DEP, entity="KuCoin", confidence=0.9025)
    write_result(tmp_path / "derived", DiscoveryResult("tron", {}, [a]), name="run_a")
    write_result(tmp_path / "derived", DiscoveryResult("tron", {}, [b]), name="run_b")
    db = tmp_path / "labels.duckdb"
    stats = build_labels(db, FIX / "wa", FIX / "dune.csv", derived_dir=tmp_path / "derived")
    with LabelStore(db) as store:
        assert store.lookup(REAL_DEP, "tron") is None
    assert stats["derived_conflicting"] == 2 and "derived" not in stats["by_tier"]


def test_label_build_arithmetic_with_an_invalid_derived_address(tmp_path, one):
    bad = finding(one, address="Tnot-a-real-address", entity="CoinDCX", confidence=0.68)
    good = finding(one, address=REAL_DEP, entity="CoinDCX", confidence=0.68)
    write_result(tmp_path / "derived", DiscoveryResult("tron", {}, [bad, good]))
    stats = build_labels(tmp_path / "l.duckdb", FIX / "wa", FIX / "dune.csv",
                         derived_dir=tmp_path / "derived")
    assert stats["by_tier"]["derived"] == 1 and stats["derived_shadowed"] == 0
    assert stats["invalid_dropped"] == 2          # the fixture's truncated row + this one
    assert stats["duplicates_dropped"] == 1       # unchanged by the derived rows


@pytest.mark.parametrize("confidence", [0.0, 1.7, -0.2])
def test_a_derived_row_with_an_impossible_confidence_stops_the_build(tmp_path, one, confidence):
    write_result(tmp_path / "derived", DiscoveryResult("tron", {}, [
        finding(one, address=REAL_DEP, entity="CoinDCX", confidence=confidence)]))
    with pytest.raises(ValueError, match="confidence"):
        build_labels(tmp_path / "l.duckdb", FIX / "wa", FIX / "dune.csv",
                     derived_dir=tmp_path / "derived")


def test_a_csv_that_is_not_a_discovery_file_is_ignored(tmp_path, one):
    (tmp_path / "derived").mkdir()
    (tmp_path / "derived" / "notes.csv").write_text("a,b\n1,2\n")
    stats = build_labels(tmp_path / "l.duckdb", FIX / "wa", FIX / "dune.csv",
                         derived_dir=tmp_path / "derived")
    assert stats["derived_loaded"] == 0


# ------------------------------------------------- 3. stations look at every fired address
def test_a_payer_is_judged_on_every_address_it_serves_not_only_the_unconfirmed():
    rows, gas_events = [], {}
    for i in range(30):          # 30 ExB addresses, also paid by ExB's own labelled wallet
        rows += deposit_and_sweep(10 * i + 1, f"B{i:02d}", "BHOT", i)
        gas_events[f"B{i:02d}"] = [ev("RENTAL", i + 4), ev("BHOT", i + 4)]
    for i in range(10):          # 10 ExA addresses paid by the same payer only
        rows += deposit_and_sweep(1000 + 10 * i, f"A{i:02d}", "HOT", 100 + i)
        gas_events[f"A{i:02d}"] = [ev("RENTAL", 104 + i)]
    result = run(rows, gas_events)
    assert [(s["address"], s["entity"], s["addresses"], s["share"]) for s in result.stations] \
        == []                    # 75% ExB is under the 95% bar: nobody's station
    assert by_address(result)["A00"].rule == "sweep"


def test_a_confirmed_address_also_paid_by_another_exchanges_station_is_a_conflict():
    rows, gas_events = [], {}
    for i in range(20):
        rows += deposit_and_sweep(10 * i + 1, f"A{i:02d}", "HOT", i)
        gas_events[f"A{i:02d}"] = [ev("STATION", i + 4)]
    rows += deposit_and_sweep(900, "ODD", "BHOT", 50)
    gas_events["ODD"] = [ev("BHOT", 54), ev("STATION", 54)]      # its own exchange AND ExA's
    odd = by_address(run(rows, gas_events))["ODD"]
    assert odd.status == "conflict" and odd.gas_payer == "STATION"
    assert odd.gas_payer_entity == "ExA"


# ------------------------------------------------- 4. the station's own kinds
def test_evidence_for_a_station_names_what_the_station_did():
    rows, gas_events = [], {}
    for i in range(10):
        rows += deposit_and_sweep(10 * i + 1, f"D{i}", "HOT", i)
        gas_events[f"D{i}"] = [ev("STATION", i + 4, kind="native")]
    # D0's sweep is also signed by someone else, who is the more frequent payer there
    gas_events["D0"].append(GasEvent(T0 + timedelta(minutes=5), "SIGNER", "signer", "tx2"))
    result = run(rows, gas_events)
    d0 = by_address(result)["D0"]
    assert d0.gas_payer == "STATION" and d0.gas_kinds == "native"
    assert "STATION, derived as a ExA gas station, sent the fee money" in d0.evidence
    assert result.stations[0]["kinds"] == "native"


# ------------------------------------------------- 5. stats add up per exchange
def test_every_candidate_is_counted_once_under_the_exchange_whose_wallet_surfaced_it():
    # C pays into ExA's wallet once but forwards 99.5% to ExB
    rows = [tx(1, "U", "C", 1000, 0), tx(2, "C", "HOT", 5, 1), tx(3, "C", "BHOT", 995, 2),
            *deposit_and_sweep(10, "D1", "HOT", 5),
            tx(20, "U", "W", 1000, 6), tx(21, "W", "HOT", 10, 7)]
    result = run(rows)
    a = result.stats["ExA"]
    assert a["candidates"] == 3
    assert a["candidates"] == a["fired"] + sum(a["rejected"].values()) + a["errors"]
    assert a["fired"] == a["derived"] + a["conflict"] + a["known"] == 2
    assert result.totals["labels_by_exchange"] == {"ExA": 1, "ExB": 1}
    assert "ExB" in result.stats and result.stats["ExB"]["candidates"] == 0


def test_a_run_limited_to_some_exchanges_writes_no_finding_for_another():
    rows = [tx(1, "U", "C", 1000, 0), tx(2, "C", "HOT", 5, 1), tx(3, "C", "BHOT", 995, 2)]
    result = run(rows, entities=("ExA",))
    assert result.findings == []
    assert result.stats["ExA"]["rejected"] == {"forwards to an exchange outside this run": 1}


def test_seed_fetch_failures_are_counted_apart_from_candidate_failures():
    chain = Chain(deposit_and_sweep(1, "D1", "HOT", 0), fail=("BHOT", "D1"))
    result = discover(CHAIN, chain, chain, Labels(CRAWL_LABELS), CrawlConfig(window_start=T0))
    assert result.stats["ExB"]["seed_errors"] == 1 and result.stats["ExB"]["errors"] == 0
    assert result.stats["ExA"]["errors"] == 1 and result.stats["ExA"]["seed_errors"] == 0


# ------------------------------------------------- 6. a listing that was cut short
def test_a_cut_listing_is_said_so_in_the_evidence():
    rows = deposit_and_sweep(1, "D1", "HOT", 0) + [tx(5, "U", "D1", 7, 30),
                                                   tx(6, "D1", "X", 100000, 40)]
    cut = by_address(run(rows, candidate_limit=2))["D1"]
    assert cut.complete is False and cut.status == "derived"
    assert "Only its first 2 transfers since " in cut.evidence
    whole = run(deposit_and_sweep(1, "D1", "HOT", 0))
    assert by_address(whole)["D1"].complete is True
    assert "Only its first" not in by_address(whole)["D1"].evidence


def test_a_cut_gas_listing_also_marks_the_finding_incomplete():
    chain = Chain(deposit_and_sweep(1, "D1", "HOT", 0))
    chain.gas_events = lambda address, since=None, limit=None: GasList([], complete=False)
    result = discover(CHAIN, chain, chain, Labels(CRAWL_LABELS), CrawlConfig(window_start=T0))
    assert result.findings[0].complete is False
    assert "gas listing" in result.findings[0].evidence


# ------------------------------------------------- minor: order must not matter
def test_outflows_sharing_a_time_and_hash_are_ordered_the_same_way_every_time():
    # only 100 arrived, 200 leaves in one transaction: which outflow took the deposit?
    rows = [tx(1, "U", A, 100, 0), replace(tx(2, A, "HOT", 100, 5), tx_hash="same"),
            replace(tx(3, A, "X", 100, 5), tx_hash="same")]
    one = sweep_rule(A, rows, LABELS, CFG)
    two = sweep_rule(A, list(reversed(rows)), LABELS, CFG)
    assert (one.share, one.fired, one.forwarded) == (two.share, two.fired, two.forwarded)
    assert one.share == D(1)        # by recipient name: "HOT" sorts before "X"
