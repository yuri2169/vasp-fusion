"""The deposit-address features on toy transfers, one behaviour per test (see tracekit.py).
Real addresses are covered by tests/test_classify_real.py on recorded responses."""
import math
import random
from datetime import timedelta

import pytest

from tracekit import T0, ToyLabels, tx
from vaspfusion.chains.base import GasEvent
from vaspfusion.classify.features import (FEATURES, LABEL_FEATURES, address_features,
                                          top_recipient)

A = "DEP"
LABELS = ToyLabels({
    "HOT": ("ExA", "exchange", "hot", "curated"),
    "PAYA": ("ExA", "exchange", "hot", "curated"),
    "BHOT": ("ExB", "exchange", "hot", "curated"),
    "ADEP": ("ExA", "exchange", "deposit", "derived"),
}).labels


def energy(payer, minute, n=0):
    return GasEvent(T0 + timedelta(minutes=minute), payer, "energy", f"gas{n}")


def deposit_address():
    rows = [tx(1, "C1", A, 100, 0), tx(2, A, "HOT", 100, 3),
            tx(3, "C2", A, 50, 10), tx(4, A, "HOT", 50, 12),
            tx(5, "C1", A, 70, 20), tx(6, A, "HOT", 70, 25)]
    events = [energy("PAYER", 2, 1), energy("PAYER", 11, 2), energy("PAYER", 24, 3)]
    return rows, events


def test_a_deposit_address_forwards_everything_to_one_wallet_on_someone_elses_gas():
    f = address_features(A, *deposit_address())
    assert f["forward_ratio"] == 1.0
    assert f["top_recipient_share"] == 1.0
    assert f["left_share"] == 0.0
    assert f["gas_outside_share"] == 1.0
    assert f["gas_payers"] == 1
    assert (f["n_senders"], f["n_recipients"], f["n_in"], f["n_out"]) == (2, 1, 3, 3)
    assert f["out_per_in"] == 1.0
    assert f["dwell_median_s"] == 180            # waits of 3, 2 and 5 minutes
    assert f["sweep_gap_cv"] == pytest.approx(2 / 11)   # gaps of 9 and 13 minutes
    assert f["stable_share"] == 1.0
    assert "age_days" not in f          # a listing's time span is the fetch window's, not
    assert "age_days" not in FEATURES   # the address's: it is not a feature
    assert f["first_ts"] == T0
    assert f["n_rows"] == 6


def test_a_customer_wallet_splits_what_it_got_and_pays_its_own_fee():
    rows = [tx(1, "X", A, 100, 0), tx(2, A, "D1", 60, 100), tx(3, A, "D2", 30, 200)]
    f = address_features(A, rows, [])
    assert f["forward_ratio"] == pytest.approx(0.6)     # D1 took the most (tie: first by name)
    assert f["top_recipient_share"] == 0.5
    assert f["left_share"] == pytest.approx(0.1)
    assert f["gas_outside_share"] == 0.0
    assert f["gas_payers"] == 0
    assert math.isnan(f["sweep_gap_cv"])                # under three outflows


def test_a_hot_wallet_pays_out_to_many():
    rows = [tx(0, "X", A, 1000, 0)] + [tx(i, A, f"R{i}", 10, i) for i in range(1, 6)]
    f = address_features(A, rows, [])
    assert f["n_recipients"] == 5
    assert f["top_recipient_share"] == pytest.approx(0.2)
    assert f["left_share"] == pytest.approx(0.95)


def test_outflows_with_no_deposit_before_them_leave_the_ratios_empty():
    f = address_features(A, [tx(1, A, "HOT", 100, 5), tx(2, A, "HOT", 5, 9)], [])
    assert math.isnan(f["forward_ratio"]) and math.isnan(f["left_share"])
    assert math.isnan(f["out_per_in"]) and math.isnan(f["dwell_median_s"])
    assert (f["n_in"], f["n_out"]) == (0, 2)


def test_dust_and_self_transfers_are_not_behaviour():
    rows, events = deposit_address()
    noisy = rows + [tx(90, "SPAM", A, "0.01", 1), tx(91, A, A, 500, 2),
                    tx(92, "SPAM", A, 0, 3, asset="FAKE@0xabc")]
    assert address_features(A, noisy, events) == address_features(A, rows, events)


def test_an_address_with_nothing_usable_is_not_an_example():
    assert address_features(A, [tx(1, "SPAM", A, "0.01", 1)], []) is None
    assert address_features(A, [], []) is None


def test_each_asset_is_paired_on_its_own():
    rows = [tx(1, "C1", A, 100, 0), tx(2, A, "HOT", 100, 3),
            tx(3, "C1", A, 2, 5, asset="COIN")]            # the coin never leaves
    f = address_features(A, rows, [])
    assert f["forward_ratio"] == 1.0                     # judged on the asset that moved
    assert f["left_share"] == 0.5                        # one of its two deposits is still there
    assert f["stable_share"] == pytest.approx(2 / 3)
    # an outflow of one asset never uses up a deposit of another
    g = address_features(A, [tx(1, "C1", A, 100, 0), tx(2, A, "HOT", 5, 3, asset="COIN")], [])
    assert math.isnan(g["forward_ratio"]) and g["left_share"] == 1.0


def test_the_order_of_the_input_rows_does_not_matter():
    rows, events = deposit_address()
    want = address_features(A, rows, events)
    rng = random.Random(7)
    for _ in range(5):
        rng.shuffle(rows)
        rng.shuffle(events)
        assert address_features(A, rows, events) == want


def test_label_features_read_the_exchange_wallets_it_touches():
    rows, _ = deposit_address()
    events = [energy("PAYA", 11, 1)]         # before the sweeps at minutes 12 and 25, not 3
    f = address_features(A, rows, events, LABELS)
    assert f["to_exchange_share"] == 1.0
    assert f["gas_from_exchange_share"] == pytest.approx(2 / 3)
    assert f["label_entity"] == "ExA"
    # a derived deposit label is not an exchange wallet: paying into it says nothing
    g = address_features(A, [tx(1, "X", A, 9, 0), tx(2, A, "ADEP", 9, 1)], [], LABELS)
    assert g["to_exchange_share"] == 0.0 and g["label_entity"] is None


def test_a_hidden_exchange_leaves_no_trace_in_the_label_features():
    rows, _ = deposit_address()
    events = [energy("PAYA", 2, 1)]
    f = address_features(A, rows, events, LABELS, hidden=("ExA",))
    assert f["to_exchange_share"] == 0.0 and f["gas_from_exchange_share"] == 0.0
    assert f["label_entity"] is None
    shown = address_features(A, rows, events, LABELS)
    assert {k: f[k] for k in FEATURES} == {k: shown[k] for k in FEATURES}


def test_behaviour_features_never_read_a_label():
    rows, events = deposit_address()
    with_labels = address_features(A, rows, events, LABELS)
    without = address_features(A, rows, events)
    assert {k: with_labels[k] for k in FEATURES} == {k: without[k] for k in FEATURES}
    assert not set(FEATURES) & set(LABEL_FEATURES)


# ------------------------------------------------------------------ the wallet it pays most
def collector():
    """HOT's own listing: it collects from many deposit addresses and pays out now and then."""
    return [tx(100 + i, f"D{i}", "HOT", 50, i) for i in range(12)] + \
        [tx(200, "HOT", "COLD", 400, 30), tx(201, A, "HOT", 100, 3)]


def test_the_top_recipient_is_the_wallet_that_took_the_most_outgoing_transfers():
    rows, _ = deposit_address()
    assert top_recipient(A, rows) == "HOT"
    assert top_recipient(A, [tx(1, "X", A, 5, 0)]) is None                 # it sent nothing
    split = [tx(1, A, "R2", 5, 0), tx(2, A, "R1", 5, 1), tx(3, A, "R2", 0, 2, asset="F@0x1")]
    assert top_recipient(A, split) == "R1"          # a tie: first by address; dust is no vote


def test_a_deposit_address_forwards_into_a_wallet_that_many_wallets_pay():
    rows, events = deposit_address()
    f = address_features(A, rows, events, recipient_rows=collector())
    assert f["recipient_forwards_on"] == 0.0        # HOT keeps most of what it collects


def test_a_customer_that_forwards_everything_pays_a_wallet_few_others_pay():
    # the look-alike: forwards 100% to one wallet too, but that wallet is a deposit address
    rows = [tx(1, "X", A, 100, 0), tx(2, A, "DEP2", 100, 5)]
    deposit = [tx(2, A, "DEP2", 100, 5), tx(3, "DEP2", "HOT", 100, 9)]
    f = address_features(A, rows, [], recipient_rows=deposit)
    assert f["forward_ratio"] == 1.0                # the same as a deposit address...
    assert f["recipient_forwards_on"] == 1.0        # ...but what it pays forwards it all on


def test_without_the_recipients_listing_its_features_are_empty_not_zero():
    rows, events = deposit_address()
    f = address_features(A, rows, events)
    assert math.isnan(f["recipient_forwards_on"])
    g = address_features(A, [tx(1, "X", A, 5, 0)], [], recipient_rows=[])
    assert math.isnan(g["recipient_forwards_on"])


def test_the_recipient_feature_cannot_tell_one_collector_from_another():
    """Every deposit address of an exchange pays the same collector. A number that
    described the collector exactly would be the same for all of them and would let the
    model memorise which collector it is, which is reading the label by the back door."""
    rows, events = deposit_address()
    other = [tx(300 + i, f"Z{i}", "HOT", 9, i) for i in range(40)] + [tx(400, "HOT", "C", 5, 50)]
    a = address_features(A, rows, events, recipient_rows=collector())
    b = address_features(A, rows, events, recipient_rows=other)
    assert a["recipient_forwards_on"] == b["recipient_forwards_on"] == 0.0
    assert {k: a[k] for k in FEATURES} == {k: b[k] for k in FEATURES}
    assert set(FEATURES) & {"recipient_senders", "recipient_forward_ratio"} == set()


def test_the_recipient_features_read_no_label():
    rows, events = deposit_address()
    with_labels = address_features(A, rows, events, LABELS, recipient_rows=collector())
    without = address_features(A, rows, events, recipient_rows=collector())
    assert {k: with_labels[k] for k in FEATURES} == {k: without[k] for k in FEATURES}
    assert "recipient_forwards_on" in FEATURES
