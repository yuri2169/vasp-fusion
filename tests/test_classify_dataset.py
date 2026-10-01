"""The training set of the deposit-address model: who is in it, and that both classes
are read the same way. Toy transfers pin the logic; real rows are in test_classify_real.py."""
from datetime import timedelta

from test_discover_crawl import Chain, Labels, deposit_and_sweep, ev
from tracekit import CHAIN, T0, tx
from vaspfusion.chains.base import ProviderError
from vaspfusion.classify.dataset import (DatasetConfig, TaggedConfig, build, build_tagged,
                                         load_runs, read_dataset, write_dataset)
from vaspfusion.classify.features import FEATURES, LABEL_FEATURES
from vaspfusion.discover.crawl import CrawlConfig, discover
from vaspfusion.discover.store import write_result

LABELS = {
    "HOT": ("ExA", "exchange", "hot", "curated"),
    "BHOT": ("ExB", "exchange", "reserve", "published_por"),
    "BAD": ("Lazarus", "sanctioned"),
    "TAGGED": ("ExA", "exchange", "deposit", "explorer_tag"),
}


class Store(Labels):
    def non_deposit(self, chain):
        return sorted((l for l in self.labels.values()
                       if l.tier != "derived" and l.kind != "deposit"), key=lambda l: l.address)


def world():
    """Two ExA deposit addresses and one of ExB, their customers, and what the customers
    and the labelled wallets did."""
    rows = (deposit_and_sweep(1, "D1", "HOT", 0, user="U1")
            + deposit_and_sweep(3, "D2", "HOT", 10, user="U2")
            + deposit_and_sweep(5, "E1", "BHOT", 20, user="U3")
            + [tx(7, "BHOT", "D1", 40, 30), tx(8, "D1", "HOT", 40, 35),      # a labelled sender
               tx(9, "D2", "D1", 5, 36), tx(10, "D1", "HOT", 5, 37),         # a finding as sender
               tx(11, "X", "U1", 300, -5), tx(12, "U1", "Y", 50, 40),        # U1's own life
               tx(13, "BAD", "Z", 9, 40),
               tx(14, "U4", "D1", 7, 41), tx(15, "D1", "HOT", 7, 42)])
    return rows


def runs_of(rows, tmp_path, gas=None, fail=()):
    chain = Chain(rows, gas or {"D1": [ev("PAY", 4)]}, fail=fail)
    result = discover(CHAIN, chain, chain, Store(LABELS), CrawlConfig(window_start=T0))
    write_result(tmp_path / "derived", result)
    chain.calls.clear()
    chain.gas_calls.clear()
    return load_runs(tmp_path / "derived"), chain


def built(tmp_path, cfg=DatasetConfig(), rows=None, fail=()):
    runs, chain = runs_of(rows or world(), tmp_path)
    chain.fail = set(fail)
    examples, stats = build(runs, chain, chain, Store(LABELS), cfg)
    return {e["address"]: e for e in examples}, stats, chain


def test_a_run_carries_its_fetch_protocol(tmp_path):
    (run,), _ = runs_of(world(), tmp_path)
    assert run.name == CHAIN and run.limit == 50
    assert run.since == T0 - timedelta(days=7)
    assert sorted(f.address for f in run.findings) == ["D1", "D2", "E1"]


def test_positives_are_the_derived_addresses_grouped_by_their_exchange(tmp_path):
    ex, stats, _ = built(tmp_path)
    assert {a: (e["y"], e["group"], e["source"]) for a, e in ex.items() if e["y"] == 1} == {
        "D1": (1, "ExA", "derived"), "D2": (1, "ExA", "derived"), "E1": (1, "ExB", "derived")}
    assert ex["D1"]["forward_ratio"] == 1.0 and ex["D1"]["gas_outside_share"] == 1.0
    assert ex["D1"]["run"] == CHAIN and ex["D1"]["first_ts"] == T0
    assert stats["positives"] == 3


def test_customers_are_the_unlabelled_senders_that_are_not_findings(tmp_path):
    ex, stats, _ = built(tmp_path)
    customers = {a: e["group"] for a, e in ex.items() if e["source"] == "customer"}
    # BHOT is labelled and D2 is a finding: neither is an ordinary wallet
    assert customers == {"U1": "ExA", "U2": "ExA", "U3": "ExB", "U4": "ExA"}
    assert all(ex[a]["y"] == 0 for a in customers)
    assert ex["U1"]["n_recipients"] == 2 and ex["U1"]["n_senders"] == 1
    assert stats["customers_seen"] == 4


def test_labelled_wallets_that_are_not_deposit_addresses_are_negatives(tmp_path):
    ex, _, _ = built(tmp_path)
    assert (ex["HOT"]["y"], ex["HOT"]["group"], ex["HOT"]["source"]) == \
        (0, "ExA", "labelled:exchange")
    assert (ex["BAD"]["y"], ex["BAD"]["group"], ex["BAD"]["source"]) == \
        (0, "other", "labelled:sanctioned")
    assert "TAGGED" not in ex                 # a tagged deposit address is not a negative


def test_the_customer_sample_is_capped_per_exchange_and_seeded(tmp_path):
    rows = world() + [r for i in range(20) for r in
                      (tx(100 + 2 * i, f"V{i:02d}", "D2", 3, 60 + i),
                       tx(101 + 2 * i, "D2", "HOT", 3, 61 + i))]
    cfg = DatasetConfig(per_exchange=5)
    a, stats, _ = built(tmp_path / "a", cfg, rows)
    b, _, _ = built(tmp_path / "b", cfg, list(reversed(rows)))
    picked = sorted(x for x, e in a.items() if e["source"] == "customer" and e["group"] == "ExA")
    assert len(picked) == 5 and stats["customers_seen"] == 24
    assert picked == sorted(x for x, e in b.items()
                            if e["source"] == "customer" and e["group"] == "ExA")
    c, _, _ = built(tmp_path / "c", DatasetConfig(per_exchange=5, seed=1), rows)
    assert picked != sorted(x for x, e in c.items()
                            if e["source"] == "customer" and e["group"] == "ExA")


def test_both_classes_are_read_with_the_same_calls(tmp_path):
    _, _, chain = built(tmp_path)
    ex, _, chain = built(tmp_path / "again")
    shapes = {address: (direction, since, asset) for address, direction, since, asset in chain.calls}
    assert len(set(shapes.values())) == 1                  # one protocol for every address
    assert set(chain.gas_calls) == set(ex)                 # and a gas listing for each example
    # the wallets they pay most are read the same way, without a gas listing
    assert set(shapes) - set(ex) and set(shapes) - set(ex) <= {"Y", "Z", "W", "P"}


def test_nothing_after_the_runs_last_positive_transfer_is_read(tmp_path):
    # the customers are fetched later than the positives were: what happened since is cut
    late = world() + [tx(50, "U2", "W", 99, 600)]
    ex, _, _ = built(tmp_path, rows=late)
    assert ex["U2"]["n_out"] == 1 and ex["U2"]["n_rows"] == 1


def test_every_address_is_judged_on_the_same_length_of_history(tmp_path):
    # one discovery run looked back 16 months, the others two weeks: without a common
    # horizon the time span of a listing would say which run an address came from
    day = 24 * 60
    rows = world() + [tx(60, "U2", "W", 5, 20 * day), tx(61, "X", "D2", 7, 20 * day),
                      tx(62, "D2", "HOT", 7, 20 * day + 5)]
    ex, _, _ = built(tmp_path, DatasetConfig(horizon_days=14), rows)
    assert ex["U2"]["n_out"] == 1 and ex["U2"]["n_rows"] == 1        # day 20 is not read
    assert ex["D2"]["n_in"] == 1 and ex["D2"]["n_rows"] == 3
    whole, _, _ = built(tmp_path / "whole", DatasetConfig(horizon_days=None), rows)
    assert whole["U2"]["n_out"] == 2 and whole["D2"]["n_in"] == 2


def test_the_horizon_starts_at_the_first_real_transfer_not_at_dust(tmp_path):
    day = 24 * 60
    rows = world() + [tx(70, "SPAM", "U2", "0.01", -6 * day), tx(71, "U2", "W", 5, 12 * day)]
    ex, _, _ = built(tmp_path, DatasetConfig(horizon_days=14),
                     rows + [tx(72, "Q", "D2", 3, 13 * day), tx(73, "D2", "HOT", 3, 13 * day + 1)])
    assert ex["U2"]["n_out"] == 2          # day 12 is inside 14 days of its first real transfer


def test_the_wallet_an_address_pays_most_is_read_and_described(tmp_path):
    ex, stats, _ = built(tmp_path)
    # D1 pays HOT, which keeps what it collects
    assert ex["D1"]["recipient_forwards_on"] == 0.0
    # U3 pays E1, which forwards everything on: a deposit address
    assert ex["U3"]["recipient_forwards_on"] == 1.0
    assert stats["recipient_errors"] == 0 and stats["recipients_read"] >= 3


def test_a_recipient_that_cannot_be_read_leaves_its_features_empty(tmp_path):
    ex, stats, _ = built(tmp_path, fail=("HOT",))
    assert stats["recipient_errors"] >= 1
    assert ex["D1"]["recipient_forwards_on"] != ex["D1"]["recipient_forwards_on"]   # NaN
    assert ex["D1"]["forward_ratio"] == 1.0                                    # the rest stands


def test_a_customer_of_two_exchanges_is_left_out(tmp_path):
    # it would sit in the training set of a model that is said never to have seen one of them
    rows = world() + [tx(80, "V", "D1", 6, 43), tx(81, "D1", "HOT", 6, 44),
                      tx(82, "V", "E1", 6, 45), tx(83, "E1", "BHOT", 6, 46)]
    ex, stats, _ = built(tmp_path, rows=rows)
    assert "V" not in ex and stats["customers_in_two_exchanges"] == 1
    assert stats["customers_seen"] == 5


def test_an_address_that_cannot_be_read_is_counted_not_guessed(tmp_path):
    ex, stats, _ = built(tmp_path, fail=("U3",))
    assert "U3" not in ex and stats["errors"] == 1 and stats["recipient_errors"] == 0


def test_the_csv_round_trips_and_rewrites_to_the_same_bytes(tmp_path):
    ex, _, _ = built(tmp_path)
    rows = list(ex.values())
    path = write_dataset(tmp_path / "dataset.csv", rows)
    first = path.read_bytes()
    df = read_dataset(path)
    assert df.height == len(rows)
    assert set(FEATURES) | set(LABEL_FEATURES) | {"address", "y", "group", "first_ts"} \
        <= set(df.columns)
    write_dataset(tmp_path / "again.csv", list(reversed(rows)))
    assert (tmp_path / "again.csv").read_bytes() == first
    d1 = df.filter(df["address"] == "D1").to_dicts()[0]
    assert d1["forward_ratio"] == 1.0 and d1["y"] == 1 and d1["first_ts"] == T0
    assert df.filter(df["address"] == "BAD")["forward_ratio"][0] is None      # empty, not zero


def test_a_failed_address_never_breaks_the_build(tmp_path):
    runs, chain = runs_of(world(), tmp_path)

    class Flaky(Chain):
        def gas_events(self, address, since=None, limit=None):
            if address == "U1":
                raise ProviderError("gas listing failed")
            return super().gas_events(address, since, limit)

    flaky = Flaky(world())
    examples, stats = build(runs, flaky, flaky, Store(LABELS), DatasetConfig())
    assert "U1" not in {e["address"] for e in examples} and stats["errors"] == 1


# ------------------------------------------------------------------ explorer-tagged truth
TAGGED = {
    "HOT": ("ExA", "exchange", "hot", "curated"),
    "T1": ("ExA", "exchange", "deposit", "explorer_tag"),
    "T2": ("ExA", "exchange", "deposit", "explorer_tag"),
    "B1": ("ExB", "exchange", "deposit", "explorer_tag"),
    "HOTA": ("ExA", "exchange", "hot", "explorer_tag"),
    "DEFI": ("Pool", "defi", "unknown", "explorer_tag"),
}


class TagStore(Store):
    def by_tier(self, chain, tier):
        return sorted((l for l in self.labels.values() if l.tier == tier),
                      key=lambda l: l.address)


def tagged_world():
    return [tx(1, "U1", "T1", 2, 0, asset="COIN"), tx(2, "T1", "HOTA", 2, 5, asset="COIN"),
            tx(3, "U2", "T2", 80, 10), tx(4, "T2", "HOT", 80, 12),
            tx(5, "X", "B1", 9, 20), tx(6, "SPAMMER", "T1", 1, 21, asset="FAKE@0xabc"),
            tx(7, "HOTA", "T1", 1, 22, asset="COIN"), tx(8, "DEFI", "P", 3, 23),
            tx(9, "W", "U1", 5, -3, asset="COIN"), tx(10, "U2", "T1", 4, 30, asset="COIN")]


def tagged(cfg=None):
    chain = Chain(tagged_world())
    cfg = cfg or TaggedConfig(chain=CHAIN, entities=("ExA", "ExB"), n_positive=5, n_negative=4,
                              per_exchange=5)
    examples, stats = build_tagged(chain, TagStore(TAGGED), cfg)
    return {e["address"]: e for e in examples}, stats, chain


def test_explorer_tagged_deposit_addresses_are_the_positives():
    ex, stats, _ = tagged()
    assert {a: (e["group"], e["source"]) for a, e in ex.items() if e["y"] == 1} == {
        "T1": ("ExA", "explorer_tag"), "T2": ("ExA", "explorer_tag"),
        "B1": ("ExB", "explorer_tag")}
    assert stats["positives"] == 3
    # judged without its own tag, with the exchange's other wallets visible
    assert ex["T1"]["to_exchange_share"] == 1.0 and ex["T1"]["label_entity"] == "ExA"


def test_tagged_wallets_that_are_not_deposit_addresses_and_customers_are_the_negatives():
    ex, stats, _ = tagged()
    negatives = {a: (e["group"], e["source"]) for a, e in ex.items() if e["y"] == 0}
    assert negatives == {"HOTA": ("ExA", "labelled:exchange"), "DEFI": ("other", "labelled:defi"),
                         "U1": ("ExA", "customer"), "U2": ("ExA", "customer"),
                         "X": ("ExB", "customer")}
    # the sender of an unknown token is spam, not a customer; a labelled sender is not one
    assert "SPAMMER" not in ex and stats["customers_seen"] == 3
    assert stats["customers_in_two_exchanges"] == 0


def test_tagged_addresses_are_all_read_with_one_protocol():
    ex, _, chain = tagged()
    assert {(d, since, asset) for _, d, since, asset in chain.calls} == {("both", None, None)}
    assert set(chain.gas_calls) == set(ex)        # the wallets they pay most need no gas listing
    assert set(ex) < {a for a, *_ in chain.calls}


def test_the_tagged_sample_is_seeded():
    cfg = TaggedConfig(chain=CHAIN, entities=("ExA",), n_positive=1, n_negative=4, per_exchange=5)
    a, _, _ = tagged(cfg)
    b, _, _ = tagged(cfg)
    assert sorted(a) == sorted(b)
    assert sum(e["y"] for e in a.values()) == 1
