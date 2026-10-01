"""The hold-out evaluation: hide the explorer tags, run the rules, compare.
Toy transfers pin the bookkeeping; real tagged addresses are in test_discover_real_eval.py."""
from datetime import timedelta

from test_discover_crawl import Chain, deposit_and_sweep
from tracekit import CHAIN, T0, ToyLabels, tx
from vaspfusion.chains.base import GasEvent
from vaspfusion.discover.evaluate import EvalConfig, evaluate, sample

LABELS = {
    "HOT": ("ExA", "exchange", "hot", "curated"),
    "BHOT": ("ExB", "exchange", "hot", "curated"),
    # explorer-tagged deposit addresses of ExA: the held-out truth
    **{f"P{i}": ("ExA", "exchange", "deposit", "explorer_tag") for i in range(6)},
    # explorer-tagged addresses that are not deposit addresses
    **{f"X{i}": ("ExC", "exchange", "hot", "explorer_tag") for i in range(4)},
    **{f"N{i}": ("SomeDefi", "defi", "unknown", "explorer_tag") for i in range(4)},
}


class Labels(ToyLabels):
    def by_tier(self, chain, tier):
        return sorted((l for l in self.labels.values() if l.tier == tier),
                      key=lambda l: l.address)


def run(transfers, pos, neg_exchange=(), neg_other=(), gas=None, fail=(), **cfg):
    chain = Chain(transfers, gas, fail)
    return evaluate(chain, Labels(LABELS), list(pos), list(neg_exchange), list(neg_other),
                    EvalConfig(chain=CHAIN, entity="ExA", **cfg))


def test_a_held_out_deposit_address_the_rules_rediscover_is_a_true_positive():
    r = run(deposit_and_sweep(1, "P0", "HOT", 0), pos=["P0"])
    assert r.rows[0] == {"address": "P0", "truth": "deposit", "tag": "ExA",
                         "outcome": "derived", "entity": "ExA", "rule": "sweep",
                         "gas": "none", "reason": None}
    assert (r.metrics["true_positives"], r.metrics["recall"]) == (1, 1.0)


def test_its_own_tag_is_hidden_so_it_is_derived_not_known():
    r = run(deposit_and_sweep(1, "P0", "HOT", 0), pos=["P0"])
    assert r.rows[0]["outcome"] == "derived"          # with the tag visible it would be "known"


def test_other_tagged_deposit_addresses_are_hidden_too():
    # P0 forwards to P1, another tagged deposit address: no hidden label may act as a seed
    r = run([tx(1, "U", "P0", 100, 0), tx(2, "P0", "P1", 100, 1)], pos=["P0"])
    assert r.rows[0]["outcome"] == "missed"
    assert r.rows[0]["reason"] == "sends nothing to a labelled exchange wallet"


def test_misses_are_counted_by_reason_and_lower_recall():
    rows = (deposit_and_sweep(1, "P0", "HOT", 0)                       # found
            + [tx(10, "U", "P1", 100, 0), tx(11, "P1", "UNLABELLED", 100, 1)]   # sweeps elsewhere
            + [tx(20, "U", "P2", 5, 0, "COIN")])                       # no stablecoin at all
    r = run(rows, pos=["P0", "P1", "P2", "P3"])
    m = r.metrics
    assert m["positives"] == 4 and m["true_positives"] == 1 and m["recall"] == 0.25
    assert m["positives_with_stablecoin_activity"] == 2
    assert m["recall_with_stablecoin_activity"] == 0.5
    assert m["missed_by_reason"] == {"no stablecoin transfers": 2,
                                     "sends nothing to a labelled exchange wallet": 1}


def test_a_deposit_address_derived_for_the_wrong_exchange_counts_against_precision():
    rows = deposit_and_sweep(1, "P0", "HOT", 0) + deposit_and_sweep(3, "P1", "BHOT", 5)
    r = run(rows, pos=["P0", "P1"])
    assert [x["outcome"] for x in r.rows] == ["derived", "wrong_entity"]
    assert r.metrics["wrong_entity"] == 1 and r.metrics["entity_precision"] == 0.5
    assert r.metrics["recall"] == 0.5


def test_a_tagged_non_deposit_address_the_rules_fire_on_is_a_false_positive():
    # X0 is an exchange wallet that moves everything to HOT; N0 does nothing of the kind
    rows = deposit_and_sweep(1, "X0", "HOT", 0) + [tx(5, "U", "N0", 100, 0)]
    r = run(rows, pos=[], neg_exchange=["X0", "X1"], neg_other=["N0", "N1"])
    m = r.metrics
    assert [x["outcome"] for x in r.rows] == ["false_positive", "true_negative",
                                              "true_negative", "true_negative"]
    assert m["false_positive_rate"] == {"exchange_wallets": 0.5, "other_tagged": 0.0}
    assert m["false_positives"] == 1 and m["negatives"] == 4
    assert r.rows[0]["tag"] == "ExC" and r.rows[0]["truth"] == "exchange_wallet"


def test_a_negatives_own_label_is_hidden_from_the_rules():
    # X0 is itself an exchange seed; with its label visible the crawler would skip it, and
    # P0's sweep to X1 (another visible exchange wallet) still counts as ExC, not ExA
    r = run(deposit_and_sweep(1, "P0", "X1", 0), pos=["P0"])
    assert r.rows[0]["outcome"] == "wrong_entity" and r.rows[0]["entity"] == "ExC"


def test_precision_combines_true_and_false_positives():
    rows = (deposit_and_sweep(1, "P0", "HOT", 0) + deposit_and_sweep(3, "P1", "HOT", 5)
            + deposit_and_sweep(5, "P2", "HOT", 10) + deposit_and_sweep(7, "X0", "HOT", 15))
    r = run(rows, pos=["P0", "P1", "P2"], neg_exchange=["X0"], neg_other=["N0"])
    assert r.metrics["precision_in_sample"] == 0.75        # 3 right of 4 fired


def test_the_gas_rule_splits_the_true_positives():
    rows = deposit_and_sweep(1, "P0", "HOT", 0) + deposit_and_sweep(3, "P1", "HOT", 10)
    gas = {"P0": [GasEvent(T0 + timedelta(minutes=4), "HOT", "native", "g1")]}
    r = run(rows, pos=["P0", "P1"], gas=gas)
    assert r.metrics["true_positives_by_rule"] == {"sweep": 1, "sweep+gas": 1}


def test_a_gas_conflict_is_not_a_discovered_address():
    gas = {"P0": [GasEvent(T0 + timedelta(minutes=4), "BHOT", "native", "g1")]}
    r = run(deposit_and_sweep(1, "P0", "HOT", 0), pos=["P0"], gas=gas)
    assert r.rows[0]["outcome"] == "conflict" and r.metrics["recall"] == 0.0
    assert r.metrics["conflicts"] == 1


def test_fetch_errors_are_reported_and_left_out_of_the_rates():
    r = run(deposit_and_sweep(1, "P0", "HOT", 0), pos=["P0", "P1"], fail=("P1",))
    assert r.metrics["errors"] == 1 and r.metrics["positives"] == 1
    assert r.metrics["recall"] == 1.0


def test_no_rate_is_invented_when_there_is_nothing_to_measure():
    r = run([], pos=[], neg_exchange=[], neg_other=[])
    assert r.metrics["recall"] is None and r.metrics["precision_in_sample"] is None
    assert r.metrics["false_positive_rate"] == {"exchange_wallets": None, "other_tagged": None}


def test_the_sample_is_seeded_stratified_and_repeatable():
    labels = Labels(LABELS)
    cfg = EvalConfig(chain=CHAIN, entity="ExA", n_positive=3, n_negative=4)
    pos, neg_ex, neg_other = sample(labels, cfg)
    assert sample(labels, cfg) == (pos, neg_ex, neg_other)
    assert len(pos) == 3 and set(pos) <= {f"P{i}" for i in range(6)}
    assert len(neg_ex) == 2 and set(neg_ex) <= {f"X{i}" for i in range(4)}
    assert len(neg_other) == 2 and set(neg_other) <= {f"N{i}" for i in range(4)}
    other_seed = sample(labels, EvalConfig(chain=CHAIN, entity="ExA", n_positive=3,
                                           n_negative=4, seed=1))
    assert other_seed != (pos, neg_ex, neg_other)


def test_a_sample_larger_than_the_population_takes_everything():
    pos, neg_ex, _ = sample(Labels(LABELS), EvalConfig(chain=CHAIN, entity="ExA",
                                                       n_positive=50, n_negative=50))
    assert len(pos) == 6 and len(neg_ex) == 4
