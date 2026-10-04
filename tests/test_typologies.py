"""Typology flags over a trace: each has a wallet, figures and hashes that are in the trace.
Toy transfers (tracekit.py); the real wallets' flags are pinned in test_demo_cases.py."""
from tracekit import CHAIN, ToyLabels, ToyProvider, tagged, tx
from vaspfusion.detect.typologies import typology_flags
from vaspfusion.trace import TraceConfig, trace

LABELS = {"HOT": ("ExA", "exchange", "hot", "curated"), "BRIDGE": ("Stargate", "bridge"),
          "OFAC": ("OFAC SDN", "sanctioned")}


def flags(transfers, labels=LABELS, **cfg):
    tr = trace("S", CHAIN, ToyProvider(transfers), ToyLabels(labels), TraceConfig(**cfg))
    found = typology_flags(tr)
    hashes = {e.transfer.tx_hash for e in tr.edges}
    for f in found:
        assert set(f) - {"threat"} == {"code", "severity", "wallet", "text", "figures",
                                       "tx_hashes"}
        assert set(f["tx_hashes"]) <= hashes and (f["tx_hashes"] or f["wallet"] == "S")
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


# ---- review: regressions
def test_money_that_sat_for_hours_is_not_rapid_because_a_later_arrival_left_fast():
    # 100 waited 1,001 minutes; only the 1 that came later left within a minute
    rows = [tx(1, "S", "M", 100, 0), tx(2, "S", "M", 1, 1000), tx(3, "M", "X", 100, 1001),
            tx(4, "M", "X", 1, 1002)]
    assert "rapid_forwarding" not in codes(flags(rows))
    pooled = [tx(1, "S", "M", 100, 0), tx(2, "S", "M", 100, 5000), tx(3, "M", "X", 200, 5001)]
    assert "rapid_forwarding" not in codes(flags(pooled))


def test_the_traced_wallet_plus_one_peeling_wallet_is_not_a_peel_chain():
    rows = [tx(1, "S", "A", 80, 0), tx(2, "S", "B", 20, 1), tx(3, "A", "C", 60, 5),
            tx(4, "A", "D", 20, 6)]
    assert "peel_chain" not in codes(flags(rows))


def test_a_peel_chain_that_does_not_start_at_the_traced_wallet_is_still_found():
    rows = [tx(1, "S", "A", 1000, 0), tx(2, "A", "P1", 100, 10), tx(3, "A", "B", 900, 11),
            tx(4, "B", "P2", 100, 70), tx(5, "B", "HOT", 800, 71)]
    f = one(flags(rows), "peel_chain")
    assert f["wallet"] == "A" and f["figures"] == {"wallets": 2.0, "amount": 1000.0, "peeled": 200.0}


def test_the_traced_wallet_is_not_one_of_the_wallets_its_money_was_split_across():
    rows = [tx(1, "S", "A", 100, 0), tx(2, "S", "B", 100, 1), tx(3, "S", "W", 100, 2),
            tx(4, "A", "W", 100, 30), tx(5, "B", "W", 100, 31)]
    assert "fan_in" not in codes(flags(rows))


# ------------------------------------------------------------------ threat tags
RANSOM = tagged("RW", "Conti", "entity", "ransomware", "Conti", "ransomwhere")
TERROR = tagged("TF", "OFAC SDN", "sanctioned", "terrorism_financing", "ISIL KHORASAN",
                "ofac-sdn-xml", "OFAC SDN list, uid 18647: ISIL KHORASAN; programme FTO, SDGT.")
LISTED = tagged("SO", "OFAC SDN", "sanctioned", "sanctioned_other", "CHEIL CREDIT BANK",
                "ofac-sdn-xml")


def test_money_reaching_a_tagged_address_raises_a_named_alert():
    rows = [tx(1, "S", "M", 1000, 0), tx(2, "M", "RW", 140, 5), tx(3, "M", "HOT", 860, 6)]
    f = one(flags(rows, {**LABELS, "RW": RANSOM}), "threat_contact")
    assert f["severity"] == "high" and f["wallet"] == "RW" and f["tx_hashes"] == ["tx2"]
    assert f["text"] == ("Linked to ransomware (Conti, Ransomwhere): 2 hops away, 14% of the "
                         "funds (140 USDT) reached RW")
    assert f["figures"] == {"share": 0.14, "amount": 140.0, "hops": 2.0}
    assert f["threat"] == {"threat": "ransomware", "entity": "Conti", "source": "ransomwhere",
                           "url": None, "evidence": "the source's words"}


def test_a_tagged_funder_is_named_too():
    rows = [tx(1, "RW", "S", 300, 0), tx(2, "X", "S", 700, 1), tx(3, "S", "HOT", 1000, 9)]
    f = one(flags(rows, {**LABELS, "RW": RANSOM}), "threat_contact")
    assert f["text"] == ("Linked to ransomware (Conti, Ransomwhere): RW funded 30% of what "
                         "the wallet received (300 USDT)")


def test_a_sanctioned_address_keeps_its_flag_and_gains_its_tag():
    rows = [tx(1, "S", "TF", 1000, 0)]
    found = flags(rows, {"TF": TERROR})
    f = one(found, "sanctioned_contact")
    assert "threat_contact" not in codes(found)
    assert f["text"].endswith("1 hop away; tagged terrorism financing (ISIL KHORASAN, "
                              "OFAC SDN list)")
    assert f["threat"]["threat"] == "terrorism_financing"
    assert "programme FTO, SDGT" in f["threat"]["evidence"]


def test_a_listing_with_no_specific_threat_adds_no_words_but_keeps_the_tag():
    f = one(flags([tx(1, "S", "SO", 1000, 0)], {"SO": LISTED}), "sanctioned_contact")
    assert "tagged" not in f["text"] and f["threat"]["entity"] == "CHEIL CREDIT BANK"


def test_a_wallet_that_is_itself_tagged_says_so_first():
    tr = trace("RW", CHAIN, ToyProvider([tx(1, "RW", "HOT", 500, 0)]),
               ToyLabels({**LABELS, "RW": RANSOM}), TraceConfig())
    found = typology_flags(tr)
    assert found[0]["code"] == "threat_contact" and found[0]["wallet"] == "RW"
    assert found[0]["text"] == "The wallet itself is tagged ransomware (Conti, Ransomwhere)"


def test_an_untagged_trace_raises_no_threat_flag_and_carries_no_threat_key():
    found = flags([tx(1, "S", "OFAC", 1000, 0)])
    assert codes(found) == ["sanctioned_contact"] and "threat" not in found[0]
