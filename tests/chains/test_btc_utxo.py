"""What one address sent and received in a UTXO transaction (chains/btc.py).

The transactions here are hand-written with placeholder names ("A", "X"), one rule
each. Real transactions are covered by test_btc.py and the Bitcoin demo case."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from vaspfusion.chains.btc import (UtxoTx, coinjoin_ids, fee_share, in_transfers, out_transfers)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def utx(n, inputs, outputs, minute=0):
    return UtxoTx(txid=f"tx{n}", time=T0 + timedelta(minutes=minute),
                  inputs=tuple(inputs), outputs=tuple(outputs))


def sats(n):
    return Decimal(n).scaleb(-8)


def rows(transfers):
    return [(t.from_addr, t.to_addr, t.amount) for t in transfers]


# ------------------------------------------------------------------ outbound
def test_an_address_sent_its_share_of_each_output():
    tx = utx(1, [("A", 60_000), ("B", 40_000)], [("X", 50_000), ("Y", 30_000)])
    assert rows(out_transfers(tx, "A")) == [("A", "X", sats(30_000)), ("A", "Y", sats(18_000))]
    assert rows(out_transfers(tx, "B")) == [("B", "X", sats(20_000)), ("B", "Y", sats(12_000))]
    assert tx.fee == 20_000
    assert fee_share(tx, "A") == sats(12_000) and fee_share(tx, "B") == sats(8_000)


def test_an_output_back_to_an_input_address_is_change_not_a_transfer():
    tx = utx(2, [("A", 100_000)], [("X", 30_000), ("A", 69_000)])
    assert rows(out_transfers(tx, "A")) == [("A", "X", sats(30_000))]
    assert fee_share(tx, "A") == sats(1_000)


def test_change_to_a_co_spent_address_is_not_a_transfer_either():
    tx = utx(3, [("A", 50_000), ("B", 50_000)], [("X", 60_000), ("B", 39_000)])
    assert rows(out_transfers(tx, "A")) == [("A", "X", sats(30_000))]


def test_shares_are_rounded_down_to_a_satoshi():
    tx = utx(4, [("A", 10_000), ("B", 20_000)], [("X", 10_001)])
    assert rows(out_transfers(tx, "A")) == [("A", "X", sats(3_333))]
    assert rows(out_transfers(tx, "B")) == [("B", "X", sats(6_667))]
    # ... and the satoshi that rounding leaves over is counted with the fee, so what an
    # address put in is always exactly what it sent plus what it paid
    assert fee_share(tx, "A") == sats(10_000 - 3_333)
    assert fee_share(tx, "B") == sats(20_000 - 6_667)


def test_what_an_address_put_in_is_exactly_transfers_plus_change_plus_fee():
    tx = utx(9, [("A", 33_333), ("B", 66_667), ("C", 1)],
             [("X", 50_001), ("Y", 20_002), ("A", 10_003), (None, 7)])
    for who in "ABC":
        sent = sum(t.amount for t in out_transfers(tx, who))
        kept = sats(10_003 * tx.put_in(who) // 100_001)           # its share of the change
        lost = sats(7 * tx.put_in(who) // 100_001)                # ... and of the unspendable output
        assert sent + kept + lost + fee_share(tx, who) == sats(tx.put_in(who))


def test_two_inputs_of_one_address_count_together_and_two_outputs_to_one_address_merge():
    tx = utx(5, [("A", 10_000), ("A", 30_000), ("B", 60_000)], [("X", 20_000), ("X", 30_000)])
    assert rows(out_transfers(tx, "A")) == [("A", "X", sats(20_000))]


def test_an_address_that_funded_nothing_sent_nothing():
    tx = utx(6, [("B", 50_000)], [("X", 40_000)])
    assert out_transfers(tx, "A") == [] and fee_share(tx, "A") == 0


def test_an_output_with_no_address_is_left_out():
    tx = utx(7, [("A", 50_000)], [(None, 0), ("X", 49_000)])
    assert rows(out_transfers(tx, "A")) == [("A", "X", sats(49_000))]


def test_a_transfer_carries_the_transaction_id_time_and_coin():
    t, = out_transfers(utx(8, [("A", 50_000)], [("X", 49_000)], minute=5), "A")
    assert (t.chain, t.tx_hash, t.asset, t.amount_usd) == ("bitcoin", "tx8", "BTC", None)
    assert t.block_time == T0 + timedelta(minutes=5)


# ------------------------------------------------------------------ inbound
def test_a_payment_is_one_inbound_transfer_from_the_largest_input():
    tx = utx(10, [("C", 30_000), ("B", 70_000)], [("A", 50_000), ("D", 49_000)])
    assert rows(in_transfers(tx, "A")) == [("B", "A", sats(50_000))]


def test_equal_inputs_name_the_smaller_address():
    tx = utx(11, [("C", 50_000), ("B", 50_000)], [("A", 99_000)])
    assert rows(in_transfers(tx, "A")) == [("B", "A", sats(99_000))]


def test_change_coming_back_is_not_an_inbound_transfer():
    tx = utx(12, [("A", 100_000)], [("X", 30_000), ("A", 69_000)])
    assert in_transfers(tx, "A") == []


def test_newly_mined_coins_come_from_coinbase():
    tx = utx(13, [(None, 0)], [("A", 312_500_000)])
    assert rows(in_transfers(tx, "A")) == [("coinbase", "A", sats(312_500_000))]


# ------------------------------------------------------------------ CoinJoin
def _coinjoin(n=20):
    # five owners each bring one input and take one equal output and their own change
    owners = "ABCDE"
    return utx(n, [(o, 1_100_000 + i) for i, o in enumerate(owners)],
               [(f"mix{i}", 1_000_000) for i in range(5)]
               + [(f"chg{i}", 99_000 + i) for i in range(5)])


def test_a_coinjoin_shaped_transaction_is_recognised_and_a_payment_is_not():
    payment = utx(21, [("A", 60_000), ("B", 40_000)], [("X", 50_000), ("Y", 30_000)])
    assert coinjoin_ids([_coinjoin(), payment]) == {"tx20"}
    assert coinjoin_ids([]) == set()


def test_one_address_paying_many_equal_amounts_is_not_a_coinjoin():
    # the same shape as _coinjoin(), but every input is the one wallet's: a batch payout
    payout = utx(22, [("HOT", 1_100_000 + i) for i in range(5)],
                 [(f"cust{i}", 1_000_000) for i in range(5)]
                 + [(f"other{i}", 99_000 + i) for i in range(5)])
    assert coinjoin_ids([payout, _coinjoin()]) == {"tx20"}


def test_a_coinjoin_is_one_transfer_into_a_sink_not_a_share_of_other_peoples_outputs():
    tx = _coinjoin()
    t, = out_transfers(tx, "A", coinjoin=True)
    assert (t.from_addr, t.to_addr) == ("A", "coinjoin:tx20")
    # what A put in, less its share of the fee
    assert t.amount + fee_share(tx, "A") == sats(1_100_000)
    assert 0 < fee_share(tx, "A") < sats(2_000)


def test_a_transaction_whose_equal_outputs_are_dust_is_not_a_coinjoin():
    # seen on chain (Aug-Sep 2026): n inputs, n outputs of 546 satoshis each. A token
    # transfer, not a mix: nobody mixes 546 satoshis.
    dusty = utx(23, [(f"in{i}", 10_000 + i) for i in range(9)],
                [(f"out{i}", 546) for i in range(8)] + [("rest", 80_000)])
    assert coinjoin_ids([dusty, _coinjoin()]) == {"tx20"}


def test_coins_that_came_out_of_a_coinjoin_come_from_the_sink():
    t, = in_transfers(_coinjoin(), "mix3", coinjoin=True)
    assert (t.from_addr, t.to_addr, t.amount) == ("coinjoin:tx20", "mix3", sats(1_000_000))
