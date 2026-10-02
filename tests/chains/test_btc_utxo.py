"""What one address sent and received in a UTXO transaction (chains/btc.py).

The transactions here are hand-written with placeholder names ("A", "X"), one rule
each. Real transactions are covered by test_btc.py and the Bitcoin demo case."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from vaspfusion.chains.btc import (UtxoTx, coinjoin_ids, fee_share, in_transfers, join_like,
                                   out_transfers, sink_reason)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def utx(n, inputs, outputs, minute=0, coinbase=False):
    return UtxoTx(txid=f"tx{n}", time=T0 + timedelta(minutes=minute),
                  inputs=tuple(inputs), outputs=tuple(outputs), coinbase=coinbase)


def sats(n):
    return Decimal(n).scaleb(-8)


def rows(transfers):
    return [(t.from_addr, t.to_addr, t.amount) for t in transfers]


# ------------------------------------------------------------------ what is certain
def test_the_only_input_address_sent_every_output():
    tx = utx(1, [("A", 100_000)], [("X", 50_000), ("Y", 30_000)])
    assert rows(out_transfers(tx, "A")) == [("A", "X", sats(50_000)), ("A", "Y", sats(30_000))]
    assert tx.fee == 20_000 and fee_share(tx, "A") == sats(20_000)


def test_an_output_back_to_the_address_itself_is_change_not_a_transfer():
    tx = utx(2, [("A", 100_000)], [("X", 30_000), ("A", 69_000)])
    assert rows(out_transfers(tx, "A")) == [("A", "X", sats(30_000))]
    assert fee_share(tx, "A") == sats(1_000)


def test_many_addresses_swept_into_one_destination_each_sent_their_share_of_it():
    tx = utx(3, [("D", 60_000), ("D2", 30_000), ("HOT", 10_000)], [("COLD", 99_000)])
    assert rows(out_transfers(tx, "D")) == [("D", "COLD", sats(59_400))]
    assert rows(out_transfers(tx, "D2")) == [("D2", "COLD", sats(29_700))]
    assert fee_share(tx, "D") == sats(600)


def test_a_sweep_into_one_of_its_own_input_addresses_moves_the_others_coins_there():
    # [M, M2] -> M2: M's coins are now at M2, not "still at M"
    tx = utx(4, [("M", 70_000), ("M2", 30_000)], [("M2", 99_000)])
    assert rows(out_transfers(tx, "M")) == [("M", "M2", sats(69_300))]
    assert out_transfers(tx, "M2") == []                    # for M2 itself it is change


def test_shares_are_rounded_down_and_the_fee_share_takes_the_rest():
    tx = utx(5, [("A", 10_000), ("B", 20_000)], [("X", 10_001)])
    assert rows(out_transfers(tx, "A")) == [("A", "X", sats(3_333))]
    assert rows(out_transfers(tx, "B")) == [("B", "X", sats(6_667))]
    assert fee_share(tx, "A") == sats(10_000 - 3_333)
    assert fee_share(tx, "B") == sats(20_000 - 6_667)


def test_two_inputs_of_one_address_count_together_and_two_outputs_to_one_address_merge():
    tx = utx(6, [("A", 10_000), ("A", 30_000)], [("X", 15_000), ("X", 20_000)])
    assert rows(out_transfers(tx, "A")) == [("A", "X", sats(35_000))]


def test_an_address_that_funded_nothing_sent_nothing():
    tx = utx(7, [("B", 50_000)], [("X", 40_000)])
    assert out_transfers(tx, "A") == [] and fee_share(tx, "A") == 0


def test_a_transfer_carries_the_transaction_id_time_and_coin():
    t, = out_transfers(utx(8, [("A", 50_000)], [("X", 49_000)], minute=5), "A")
    assert (t.chain, t.tx_hash, t.asset, t.amount_usd) == ("bitcoin", "tx8", "BTC", None)
    assert t.block_time == T0 + timedelta(minutes=5)


def test_an_output_with_no_address_goes_to_a_sink_and_a_zero_one_is_ignored():
    tx = utx(9, [("A", 50_000)], [(None, 0), (None, 700), ("X", 49_000)])
    assert rows(out_transfers(tx, "A")) == [("A", "X", sats(49_000)),
                                            ("A", "no-address:tx9", sats(700))]
    assert sink_reason("no-address:tx9") == "no_address"


# ------------------------------------------------------------------ what is not
POOLED = utx(10, [("A", 60_000), ("B", 40_000)], [("X", 50_000), ("Y", 30_000)])


def test_coins_spent_with_other_addresses_coins_to_several_destinations_are_not_split():
    # which output A's coins paid is not on the chain: one row into a sink, nothing guessed
    assert rows(out_transfers(POOLED, "A")) == [("A", "pooled:tx10", sats(48_000))]
    assert rows(out_transfers(POOLED, "B")) == [("B", "pooled:tx10", sats(32_000))]
    assert sink_reason("pooled:tx10") == "pooled" and sink_reason("X") is None
    assert fee_share(POOLED, "A") == sats(12_000)


def test_change_to_a_co_spent_address_makes_it_two_destinations():
    tx = utx(11, [("A", 50_000), ("B", 50_000)], [("X", 60_000), ("B", 39_000)])
    assert rows(out_transfers(tx, "A")) == [("A", "pooled:tx11", sats(49_500))]


def test_the_traced_wallets_own_spend_is_split_in_proportion():
    # the officer's wallet: its co-spent addresses are its own, so every output is its payment
    assert rows(out_transfers(POOLED, "A", own=True)) == [("A", "X", sats(30_000)),
                                                          ("A", "Y", sats(18_000))]


def test_even_the_traced_wallets_spend_is_not_split_when_five_addresses_fund_it():
    tx = utx(12, [(f"A{i}", 20_000) for i in range(5)], [("X", 50_000), ("Y", 49_000)])
    assert rows(out_transfers(tx, "A0", own=True)) == [("A0", "pooled:tx12", sats(19_800))]


def test_nor_when_it_looks_like_a_small_join():
    # two funders, two equal outputs and change: the shape of a two-party CoinJoin
    tx = utx(13, [("A", 60_000), ("B", 50_000)], [("X", 40_000), ("Y", 40_000), ("Z", 29_000)])
    assert join_like(tx)
    assert rows(out_transfers(tx, "A", own=True)) == [("A", "pooled:tx13", sats(59_454))]
    assert not join_like(POOLED)
    assert not join_like(utx(14, [("A", 90_000)], [("X", 40_000), ("Y", 40_000)]))   # one funder


def test_what_an_address_put_in_is_exactly_transfers_plus_change_plus_fee():
    tx = utx(15, [("A", 33_333), ("B", 66_667), ("C", 1)],
             [("X", 50_001), ("Y", 20_002), ("A", 10_003), (None, 7)])
    for who, own in (("A", True), ("B", True), ("C", True), ("A", False), ("B", False)):
        sent = sum(t.amount for t in out_transfers(tx, who, own=own))
        kept = sats(10_003 * tx.put_in(who) // 100_001) if who == "A" else 0   # its own change
        assert sent + kept + fee_share(tx, who) == sats(tx.put_in(who))


# ------------------------------------------------------------------ inbound
def test_a_payment_is_one_inbound_transfer_from_the_largest_input():
    tx = utx(20, [("C", 30_000), ("B", 70_000)], [("A", 50_000), ("D", 49_000)])
    assert rows(in_transfers(tx, "A")) == [("B", "A", sats(50_000))]


def test_equal_inputs_name_the_smaller_address():
    tx = utx(21, [("C", 50_000), ("B", 50_000)], [("A", 99_000)])
    assert rows(in_transfers(tx, "A")) == [("B", "A", sats(99_000))]


def test_change_coming_back_is_not_an_inbound_transfer():
    tx = utx(22, [("A", 100_000)], [("X", 30_000), ("A", 69_000)])
    assert in_transfers(tx, "A") == []


def test_newly_mined_coins_come_from_the_block_reward():
    tx = utx(23, [(None, 0)], [("A", 312_500_000)], coinbase=True)
    assert rows(in_transfers(tx, "A")) == [("block-reward:tx23", "A", sats(312_500_000))]
    assert sink_reason("block-reward:tx23") == "mined"


def test_inputs_with_no_address_form_are_not_called_newly_mined():
    tx = utx(24, [(None, 500_000)], [("A", 499_000)])        # an old pay-to-pubkey coin
    assert rows(in_transfers(tx, "A")) == [("no-address:tx24", "A", sats(499_000))]


def test_the_esplora_coinbase_flag_is_read():
    raw = {"txid": "c" * 64, "status": {"block_time": 1_750_000_000},
           "vin": [{"is_coinbase": True, "prevout": None}],
           "vout": [{"scriptpubkey_address": "A", "value": 312_500_000}]}
    assert UtxoTx.from_esplora(raw).coinbase is True
    raw["vin"] = [{"is_coinbase": False, "prevout": {"scriptpubkey_address": "B", "value": 9}}]
    assert UtxoTx.from_esplora(raw).coinbase is False


# ------------------------------------------------------------------ CoinJoin
def _coinjoin(n=30):
    # five owners each bring one input and take one equal output and their own change
    owners = "ABCDE"
    return utx(n, [(o, 1_100_000 + i) for i, o in enumerate(owners)],
               [(f"mix{i}", 1_000_000) for i in range(5)]
               + [(f"chg{i}", 99_000 + i) for i in range(5)])


def test_a_coinjoin_shaped_transaction_is_recognised_and_a_payment_is_not():
    assert coinjoin_ids([_coinjoin(), POOLED]) == {"tx30"}
    assert coinjoin_ids([]) == set()


def test_one_address_paying_many_equal_amounts_is_not_a_coinjoin():
    # the same shape as _coinjoin(), but every input is the one wallet's: a batch payout
    payout = utx(31, [("HOT", 1_100_000 + i) for i in range(5)],
                 [(f"cust{i}", 1_000_000) for i in range(5)]
                 + [(f"other{i}", 99_000 + i) for i in range(5)])
    assert coinjoin_ids([payout, _coinjoin()]) == {"tx30"}


def test_a_transaction_whose_equal_outputs_are_dust_is_not_a_coinjoin():
    # seen on chain (Aug-Sep 2026): n inputs, n outputs of 546 satoshis each. A token
    # transfer, not a mix: nobody mixes 546 satoshis.
    dusty = utx(32, [(f"in{i}", 10_000 + i) for i in range(9)],
                [(f"out{i}", 546) for i in range(8)] + [("rest", 80_000)])
    assert coinjoin_ids([dusty, _coinjoin()]) == {"tx30"}
    assert join_like(dusty)             # ... but its inputs are still several people's


def test_the_dust_rule_reads_the_same_equal_block_as_the_shape_rule():
    # five dust outputs listed first, then five real ones: the larger block value decides
    tx = utx(33, [(o, 1_100_000 + i) for i, o in enumerate("ABCDE")],
             [(f"dust{i}", 546) for i in range(5)] + [(f"mix{i}", 1_000_000) for i in range(5)])
    assert coinjoin_ids([tx]) == {"tx33"}


def test_a_coinjoin_is_one_transfer_into_a_sink_not_a_share_of_other_peoples_outputs():
    tx = _coinjoin()
    t, = out_transfers(tx, "A", coinjoin=True)
    assert (t.from_addr, t.to_addr) == ("A", "coinjoin:tx30")
    assert t.amount + fee_share(tx, "A") == sats(1_100_000)
    assert 0 < fee_share(tx, "A") < sats(2_000)
    assert sink_reason("coinjoin:tx30") == "coinjoin"
    # also for the traced wallet itself
    assert rows(out_transfers(tx, "A", coinjoin=True, own=True)) == rows([t])


def test_coins_that_came_out_of_a_coinjoin_come_from_the_sink():
    t, = in_transfers(_coinjoin(), "mix3", coinjoin=True)
    assert (t.from_addr, t.to_addr, t.amount) == ("coinjoin:tx30", "mix3", sats(1_000_000))
