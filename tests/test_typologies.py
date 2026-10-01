"""Typology flags over a trace: each has a wallet, figures and hashes that are in the trace.
Toy transfers (tracekit.py); the real wallets' flags are pinned in test_demo_cases.py."""
from tracekit import CHAIN, ToyLabels, ToyProvider, tx
from vaspfusion.detect.typologies import typology_flags
from vaspfusion.trace import TraceConfig, trace

LABELS = {"HOT": ("ExA", "exchange", "hot", "curated"), "BRIDGE": ("Stargate", "bridge"),
          "OFAC": ("OFAC SDN", "sanctioned")}


def flags(transfers, labels=LABELS, **cfg):
    tr = trace("S", CHAIN, ToyProvider(transfers), ToyLabels(labels), TraceConfig(**cfg))
    found = typology_flags(tr)
    hashes = {e.transfer.tx_hash for e in tr.edges}
    for f in found:
        assert set(f) == {"code", "severity", "wallet", "text", "figures", "tx_hashes"}
        assert f["tx_hashes"] and set(f["tx_hashes"]) <= hashes
        assert all(isinstance(v, float) for v in f["figures"].values())
    return found


def one(found, code):
    hits = [f for f in found if f["code"] == code]
    assert len(hits) == 1, [f["code"] for f in found]
    return hits[0]


def codes(found):
    return [f["code"] for f in found]


# ------------------------------------------------------------------ fan-out
def test_five_recipients_in_a_day_is_a_fan_out():
    f = one(flags([tx(i, "S", f"R{i}", 110, i) for i in range(1, 6)]), "fan_out")
    assert f["wallet"] == "S" and f["severity"] == "info"
    assert f["figures"] == {"recipients": 5.0, "amount": 550.0, "hours": 0.07}
    assert f["tx_hashes"] == ["tx1", "tx2", "tx3", "tx4", "tx5"]
    assert "S paid 550 USDT to 5 wallets within 4 minutes" in f["text"]


def test_four_recipients_or_five_spread_over_days_is_not():
    assert "fan_out" not in codes(flags([tx(i, "S", f"R{i}", 110, i) for i in range(1, 5)]))
    slow = [tx(i, "S", f"R{i}", 110, i * 60 * 13) for i in range(1, 6)]     # 13 h apart
    assert "fan_out" not in codes(flags(slow))


def test_an_intermediary_that_spreads_the_money_is_flagged_too():
    rows = [tx(1, "S", "M", 600, 0)] + [tx(10 + i, "M", f"R{i}", 100, 5 + i) for i in range(6)]
    f = one(flags(rows), "fan_out")
    assert f["wallet"] == "M" and f["figures"]["recipients"] == 6.0


# ------------------------------------------------------------------ fan-in
def test_five_funders_is_a_fan_in():
    rows = [tx(i, f"F{i}", "S", 120, i) for i in range(1, 6)] + [tx(9, "S", "HOT", 600, 30)]
    f = one(flags(rows), "fan_in")
    assert f["wallet"] == "S" and f["figures"] == {"senders": 5.0, "amount": 600.0}
    assert f["tx_hashes"] == ["tx1", "tx2", "tx3", "tx4", "tx5"]
    assert "fan_in" not in codes(flags(rows[1:]))                    # four funders


def test_money_that_was_split_and_merges_again_is_a_fan_in():
    rows = [tx(i, "S", f"M{i}", 300, i) for i in (1, 2, 3)] \
        + [tx(10 + i, f"M{i}", "C", 300, 20 + i) for i in (1, 2, 3)]
    f = one(flags(rows), "fan_in")
    assert f["wallet"] == "C" and f["figures"] == {"senders": 3.0, "amount": 900.0}
    assert f["tx_hashes"] == ["tx11", "tx12", "tx13"]


# ------------------------------------------------------------------ rapid forwarding
def test_passing_everything_on_within_minutes_is_rapid_forwarding():
    f = one(flags([tx(1, "S", "M", 1000, 0), tx(2, "M", "HOT", 1000, 3)]), "rapid_forwarding")
    assert f["wallet"] == "M" and f["severity"] == "warn"
    assert f["figures"] == {"share": 1.0, "amount": 1000.0, "seconds": 180.0}
    assert f["tx_hashes"] == ["tx1", "tx2"]
    assert "passed on 100% of the 1,000 USDT that reached it within 3 minutes" in f["text"]


def test_slow_or_partial_forwarding_is_not_rapid():
    assert "rapid_forwarding" not in codes(
        flags([tx(1, "S", "M", 1000, 0), tx(2, "M", "HOT", 1000, 11)]))
    assert "rapid_forwarding" not in codes(
        flags([tx(1, "S", "M", 1000, 0), tx(2, "M", "HOT", 800, 3)]))


def test_each_part_is_timed_from_the_arrival_that_funded_it():
    rows = [tx(1, "S", "M", 500, 0), tx(2, "M", "HOT", 500, 2),
            tx(3, "S", "M", 500, 600), tx(4, "M", "HOT", 500, 604)]
    assert one(flags(rows), "rapid_forwarding")["figures"]["seconds"] == 240.0


# ------------------------------------------------------------------ peel chain
PEEL = [tx(1, "S", "P1", 100, 0), tx(2, "S", "A", 900, 1),
        tx(3, "A", "P2", 100, 60), tx(4, "A", "B", 800, 61),
        tx(5, "B", "P3", 100, 120), tx(6, "B", "HOT", 700, 121)]


def test_wallets_that_each_peel_a_little_and_pass_the_rest_on_are_a_peel_chain():
    f = one(flags(PEEL), "peel_chain")
    assert f["wallet"] == "S" and f["severity"] == "warn"
    assert f["figures"] == {"wallets": 3.0, "amount": 1000.0, "peeled": 300.0}
    assert f["tx_hashes"] == ["tx1", "tx2", "tx3", "tx4", "tx5", "tx6"]
    assert "S → A → B" in f["text"]


def test_one_peel_or_an_even_split_is_not_a_chain():
    assert "peel_chain" not in codes(flags(PEEL[:2] + [tx(4, "A", "HOT", 900, 61)]))
    even = [tx(1, "S", "P1", 500, 0), tx(2, "S", "A", 500, 1),
            tx(3, "A", "P2", 250, 60), tx(4, "A", "HOT", 250, 61)]
    assert "peel_chain" not in codes(flags(even))


# ------------------------------------------------------------------ round amounts
def test_mostly_round_stablecoin_amounts_are_flagged():
    rows = [tx(1, "S", "HOT", 500, 0), tx(2, "S", "HOT", 1000, 1), tx(3, "S", "HOT", 2000, 2),
            tx(4, "S", "HOT", 123.45, 3)]
    f = one(flags(rows), "round_amounts")
    assert f["wallet"] == "S" and f["severity"] == "info"
    assert f["figures"] == {"round_transfers": 3.0, "transfers": 4.0, "amount": 3500.0}
    assert f["tx_hashes"] == ["tx1", "tx2", "tx3"]


def test_two_round_amounts_or_a_minority_are_not():
    assert "round_amounts" not in codes(flags([tx(1, "S", "HOT", 500, 0), tx(2, "S", "HOT", 100, 1)]))
    rows = [tx(i, "S", "HOT", 100 * i, i) for i in (1, 2, 3)] \
        + [tx(10 + i, "S", "HOT", 17.3 + i, 10 + i) for i in range(4)]
    assert "round_amounts" not in codes(flags(rows))


def test_native_coin_amounts_are_not_judged_round():
    rows = [tx(i, "S", "HOT", 100 * i, i, asset="COIN") for i in (1, 2, 3)]
    assert "round_amounts" not in codes(flags(rows))


# ------------------------------------------------------------------ label flags, order
def test_label_flags_come_first_and_keep_their_figures():
    rows = [tx(1, "S", "OFAC", 500, 0), tx(2, "S", "BRIDGE", 300, 1), tx(3, "S", "M", 200, 2),
            tx(4, "M", "HOT", 200, 4)]
    found = flags(rows)
    assert codes(found) == ["sanctioned_contact", "bridge_hop", "rapid_forwarding",
                            "round_amounts"]
    assert found[0]["figures"] == {"share": 0.5, "amount": 500.0, "hops": 1.0}


def test_a_quiet_wallet_has_no_flags():
    assert flags([tx(1, "S", "HOT", 1234.5, 0)]) == []
