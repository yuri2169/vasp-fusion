"""The two discovery rules on toy transfers, one behaviour per test (see tracekit.py).
Real addresses are covered by tests/test_discover_crawl.py on recorded responses."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from tracekit import T0, ToyLabels, tx
from vaspfusion.chains.base import GasEvent
from vaspfusion.discover.rules import (DiscoverConfig, decide, evidence_text, gas_rule,
                                       is_seed, sweep_rule)

A = "DEP"            # the address under test
LABELS = ToyLabels({
    "HOT": ("ExA", "exchange", "hot", "curated"),
    "HOT2": ("ExA", "exchange", "reserve", "published_por"),
    "BHOT": ("ExB", "exchange", "hot", "curated"),
    "ADEP": ("ExA", "exchange", "deposit", "explorer_tag"),
    "DER": ("ExA", "exchange", "hot", "derived"),
    "OFAC": ("Lazarus", "sanctioned"),
}).labels
CFG = DiscoverConfig()


def sweep(rows, cfg=CFG, labels=LABELS):
    return sweep_rule(A, rows, labels, cfg)


def gas_ev(payer, minute, kind="energy", n=0):
    return GasEvent(time=T0 + timedelta(minutes=minute), payer=payer, kind=kind,
                    tx_hash=f"gas{n}", amount=None)


# ------------------------------------------------------------------ seeds
def test_seeds_are_vasp_wallets_that_are_neither_derived_nor_deposit_addresses():
    assert is_seed(LABELS["HOT"]) and is_seed(LABELS["HOT2"])
    assert not is_seed(LABELS["ADEP"])      # a tagged deposit address is not a hot wallet
    assert not is_seed(LABELS["DER"])       # derived labels never seed further labels
    assert not is_seed(LABELS["OFAC"])
    assert not is_seed(None)


# ------------------------------------------------------------------ sweep rule
def test_everything_received_is_forwarded_to_one_exchange():
    s = sweep([tx(1, "U1", A, 100, 0), tx(2, "U2", A, 50, 5), tx(3, A, "HOT", 150, 6)])
    assert s.fired and s.entity == "ExA" and s.target == "HOT" and s.target_tier == "curated"
    assert s.share == 1 and s.received == D(150) and s.forwarded == D(150)
    assert (s.n_deposits, s.n_senders, s.n_sweeps) == (2, 2, 1)
    assert s.median_delay_s == 210            # parts waited 360 s and 60 s
    assert [t.tx_hash for t in s.sweeps] == ["tx3"]


def test_a_wallet_that_sends_the_exchange_a_small_part_is_not_a_deposit_address():
    s = sweep([tx(1, "U1", A, 1000, 0), tx(2, A, "HOT", 10, 5)])
    assert not s.fired and s.reason == "forwards under 90% of what it receives"
    assert s.share == D("0.01")


def test_money_split_with_an_unlabelled_wallet_is_not_a_sweep():
    s = sweep([tx(1, "U1", A, 100, 0), tx(2, A, "HOT", 40, 5), tx(3, A, "X", 60, 6)])
    assert not s.fired and s.share == D("0.4")


def test_deposits_after_the_last_sweep_are_not_counted_against_it():
    s = sweep([tx(1, "U1", A, 100, 0), tx(2, A, "HOT", 100, 5), tx(3, "U2", A, 900, 30)])
    assert s.fired and s.received == D(100) and s.share == 1 and s.pending == D(900)


def test_balance_from_before_the_view_is_ignored():
    # the first sweep moves 500 that arrived before the listing starts
    s = sweep([tx(1, A, "HOT", 500, 0), tx(2, "U1", A, 100, 5), tx(3, A, "HOT", 100, 6)])
    assert s.fired and s.received == D(100) and s.forwarded == D(100) and s.n_sweeps == 2


def test_sweeps_with_no_deposit_in_view_do_not_fire():
    s = sweep([tx(1, A, "HOT", 500, 0)])
    assert not s.fired and s.reason == "no deposit seen before a sweep"


def test_no_transfer_to_any_exchange_wallet():
    s = sweep([tx(1, "U1", A, 100, 0), tx(2, A, "X", 100, 5)])
    assert not s.fired and s.reason == "sends nothing to a labelled exchange wallet"
    assert s.entity is None


def test_a_sweep_later_than_the_time_limit_does_not_count():
    late = 25 * 60
    s = sweep([tx(1, "U1", A, 100, 0), tx(2, A, "HOT", 100, late)])
    assert not s.fired and s.share == 0
    assert sweep([tx(1, "U1", A, 100, 0), tx(2, A, "HOT", 100, late)],
                 DiscoverConfig(max_hours=48)).fired


def test_dust_and_zero_value_rows_are_ignored():
    rows = [tx(1, "SPAM", A, 0, 0), tx(2, "SPAM2", A, "0.01", 1), tx(3, "U1", A, 100, 2),
            tx(4, A, "HOT", 100, 3), tx(5, A, "SPOOF", 0, 4)]
    s = sweep(rows)
    assert s.fired and s.n_senders == 1 and s.n_deposits == 1 and s.share == 1


def test_only_stablecoin_rows_count():
    rows = [tx(1, "U1", A, 100, 0), tx(2, A, "HOT", 100, 1), tx(3, "U1", A, 5000, 2, "COIN"),
            tx(4, A, "X", 5000, 3, "COIN")]
    assert sweep(rows).fired


def test_two_wallets_of_the_same_exchange_add_up_and_the_larger_is_the_target():
    s = sweep([tx(1, "U1", A, 100, 0), tx(2, A, "HOT", 30, 1), tx(3, A, "HOT2", 70, 2)])
    assert s.fired and s.entity == "ExA" and s.target == "HOT2"
    assert s.target_tier == "published_por" and s.n_sweeps == 2


def test_two_exchanges_the_larger_must_clear_the_bar_alone():
    s = sweep([tx(1, "U1", A, 100, 0), tx(2, A, "HOT", 60, 1), tx(3, A, "BHOT", 40, 2)])
    assert not s.fired and s.entity == "ExA" and s.share == D("0.6")
    assert s.other_entities == {"ExB": D(40)}


def test_derived_and_deposit_labels_are_not_sweep_targets():
    assert not sweep([tx(1, "U1", A, 100, 0), tx(2, A, "DER", 100, 1)]).fired
    assert not sweep([tx(1, "U1", A, 100, 0), tx(2, A, "ADEP", 100, 1)]).fired


def test_minimum_number_of_senders():
    rows = [tx(1, "U1", A, 100, 0), tx(2, A, "HOT", 100, 1)]
    assert sweep(rows).fired
    s = sweep(rows, DiscoverConfig(min_senders=2))
    assert not s.fired and s.reason == "fewer than 2 distinct senders"


def test_first_in_first_out_delay_per_part():
    # 100 arrives at 0, 100 at 10; one sweep of 200 at 12: parts waited 12 and 2 minutes
    s = sweep([tx(1, "U1", A, 100, 0), tx(2, "U1", A, 100, 10), tx(3, A, "HOT", 200, 12)])
    assert s.median_delay_s == (12 * 60 + 2 * 60) / 2


# ------------------------------------------------------------------ gas rule
def swept():
    return sweep([tx(1, "U1", A, 100, 0), tx(2, A, "HOT", 100, 30),
                  tx(3, "U1", A, 100, 100), tx(4, A, "HOT", 100, 130)])


def gas(events, cfg=CFG, s=None):
    s = s or swept()
    return gas_rule(A, s.sweeps, events, LABELS, s.entity, cfg)


def test_gas_paid_by_a_wallet_of_the_same_exchange_confirms():
    g = gas([gas_ev("HOT2", 29), gas_ev("HOT2", 129, n=1)])
    assert g.verdict == "confirmed" and g.payer == "HOT2" and g.payer_entity == "ExA"
    assert g.n_paid == 2 and g.kinds == ("energy",)


def test_gas_paid_by_another_exchange_is_a_conflict():
    g = gas([gas_ev("BHOT", 29)])
    assert g.verdict == "conflict" and g.payer == "BHOT" and g.payer_entity == "ExB"


def test_a_conflict_is_not_hidden_by_a_confirming_payer():
    g = gas([gas_ev("HOT2", 29), gas_ev("BHOT", 129, n=1)])
    assert g.verdict == "conflict" and g.payer_entity == "ExB"


def test_an_unlabelled_payer_is_neutral_and_named():
    g = gas([gas_ev("P", 29), gas_ev("P", 129, n=1), gas_ev("Q", 128, n=2)])
    assert g.verdict == "unlabelled" and g.payer == "P" and g.payer_entity is None
    assert g.payers == {"P": 2, "Q": 1}


def test_no_gas_event_before_any_sweep():
    assert gas([]).verdict == "none"
    assert gas([gas_ev("HOT2", 31)]).verdict == "none"        # after the sweep, not before


def test_gas_outside_the_window_does_not_count():
    assert gas([gas_ev("HOT2", 20)], DiscoverConfig(gas_window_s=300)).verdict == "none"
    assert gas([gas_ev("HOT2", 26)], DiscoverConfig(gas_window_s=300)).verdict == "confirmed"


def test_the_address_paying_its_own_gas_is_not_evidence():
    assert gas([gas_ev(A, 29)]).verdict == "none"


def test_a_sweep_signed_by_someone_else_names_the_signer_as_payer():
    s = sweep([tx(1, "U1", A, 100, 0), replace(tx(2, A, "HOT", 100, 30), fee_payer="HOT2")])
    g = gas_rule(A, s.sweeps, [], LABELS, s.entity, CFG)
    assert g.verdict == "confirmed" and g.kinds == ("signer",)


def test_a_signer_event_counts_only_for_the_sweep_it_signed():
    # another party's contract call near the sweep (a depositor's own transfer) is not gas
    stray = GasEvent(time=T0 + timedelta(minutes=29), payer="HOT2", kind="signer", tx_hash="txX")
    assert gas([stray]).verdict == "none"
    signed = GasEvent(time=T0 + timedelta(minutes=30), payer="HOT2", kind="signer", tx_hash="tx2")
    g = gas([signed])
    assert g.verdict == "confirmed" and g.kinds == ("signer",) and g.n_paid == 1


def test_a_derived_or_non_vasp_payer_counts_as_unlabelled():
    assert gas([gas_ev("DER", 29)]).verdict == "unlabelled"
    assert gas([gas_ev("OFAC", 29)]).verdict == "other_label"     # named, never a station


# ------------------------------------------------------------------ decision
@pytest.mark.parametrize("verdict, status, rule, conf", [
    ("confirmed", "derived", "sweep+gas", 0.8075),
    ("station", "derived", "sweep+station", 0.765),
    ("unlabelled", "derived", "sweep", 0.68),
    ("none", "derived", "sweep", 0.68),
    ("other_label", "derived", "sweep", 0.68),
    ("conflict", "conflict", "sweep", None),
])
def test_decision_table(verdict, status, rule, conf):
    d = decide(swept(), verdict, existing=None)
    assert (d.status, d.rule, d.confidence) == (status, rule, conf)


def test_confidence_scales_with_the_tier_of_the_sweep_target():
    s = sweep([tx(1, "U1", A, 100, 0), tx(2, A, "HOT2", 100, 1)])    # proof of reserves
    assert decide(s, "confirmed", existing=None).confidence == 0.9025


def test_an_address_already_labelled_is_a_conflict_not_an_overwrite():
    d = decide(swept(), "confirmed", existing=LABELS["OFAC"])
    assert d.status == "conflict" and d.confidence is None
    assert d.conflict == "already labelled Lazarus (sanctioned, curated)"


def test_an_address_already_labelled_for_the_same_exchange_is_known_not_new():
    d = decide(swept(), "confirmed", existing=LABELS["ADEP"])
    assert d.status == "known" and d.conflict is None


def test_an_existing_derived_label_does_not_block_a_new_run():
    assert decide(swept(), "confirmed", existing=LABELS["DER"]).status == "derived"


# ------------------------------------------------------------------ evidence text
def test_evidence_text_states_the_numbers_the_rules_used():
    s = swept()
    g = gas([gas_ev("HOT2", 29), gas_ev("HOT2", 129, n=1)])
    text = evidence_text(s, g, decide(s, g.verdict, existing=None))
    assert text == (
        "Sweep rule: forwarded 100% of the 200 USDT it received from 1 sender to ExA wallet "
        "HOT (curated list) in 2 sweeps, typically 30 minutes after arrival. "
        "Gas rule: HOT2, labelled ExA, paid the energy for 2 of 2 sweeps. "
        "Both rules agree. Rule confidence 0.81, not calibrated.")


def test_evidence_text_for_a_gas_conflict():
    s = swept()
    g = gas([gas_ev("BHOT", 29)])
    text = evidence_text(s, g, decide(s, g.verdict, existing=None))
    assert "Gas rule: BHOT, labelled ExB, paid the energy for 1 of 2 sweeps." in text
    assert text.endswith("Conflict: the rules name different exchanges. Not used as a label.")
