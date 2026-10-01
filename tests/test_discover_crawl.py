"""The crawler: seed wallets -> their senders -> the two rules -> gas stations.
Toy transfers pin the logic; the recorded real crawl is in test_discover_real.py."""
from datetime import timedelta

from tracekit import CHAIN, T0, ToyLabels, ToyProvider, tx
from vaspfusion.chains.base import GasEvent, ProviderError
from vaspfusion.discover.crawl import CrawlConfig, discover
from vaspfusion.discover.rules import DiscoverConfig, is_seed

LABELS = {
    "HOT": ("ExA", "exchange", "hot", "curated"),
    "GASA": ("ExA", "exchange", "hot", "curated"),
    "BHOT": ("ExB", "exchange", "reserve", "published_por"),
    "TAGGED": ("ExA", "exchange", "deposit", "explorer_tag"),
    "BAD": ("Lazarus", "sanctioned"),
}


class Labels(ToyLabels):
    def seeds(self, chain):
        return sorted((l for l in self.labels.values() if is_seed(l)),
                      key=lambda l: (l.entity, l.address))


class Chain(ToyProvider):
    def __init__(self, transfers, gas=None, fail=()):
        super().__init__(transfers, fail=fail)
        self.gas = gas or {}
        self.gas_calls: list[str] = []

    def gas_events(self, address, since=None, limit=None):
        self.gas_calls.append(address)
        return self.gas.get(address, [])


def ev(payer, minute, kind="energy"):
    return GasEvent(T0 + timedelta(minutes=minute), payer, kind, f"g-{payer}-{minute}")


def deposit_and_sweep(n, dep, hot, minute, amount=100, user=None):
    return [tx(n, user or f"U{n}", dep, amount, minute), tx(n + 1, dep, hot, amount, minute + 5)]


def run(transfers, gas=None, labels=LABELS, fail=(), **cfg):
    chain = Chain(transfers, gas, fail)
    cfg.setdefault("window_start", T0)
    result = discover(CHAIN, chain, chain, Labels(labels), CrawlConfig(**cfg))
    return result, chain


def by_address(result):
    return {f.address: f for f in result.findings}


def test_senders_into_a_seed_wallet_become_derived_deposit_addresses():
    rows = deposit_and_sweep(1, "D1", "HOT", 0) + deposit_and_sweep(3, "D2", "HOT", 10)
    result, _ = run(rows, gas={"D1": [ev("GASA", 4)]})
    f = by_address(result)
    assert sorted(f) == ["D1", "D2"]
    d1, d2 = f["D1"], f["D2"]
    assert (d1.entity, d1.category, d1.kind, d1.status, d1.rule) == \
        ("ExA", "exchange", "deposit", "derived", "sweep+gas")
    assert d1.confidence == 0.8075 and d1.gas_payer == "GASA" and d1.sweep_target == "HOT"
    assert (d2.status, d2.rule, d2.confidence, d2.gas_verdict) == ("derived", "sweep", 0.68, "none")
    assert d1.evidence.startswith("Sweep rule: forwarded 100% of the 100 USDT")
    assert d1.chain == CHAIN and d1.first_sweep_tx == "tx2"


def test_seed_wallets_and_the_window_are_respected():
    # HOT's own inbound from another seed is not a candidate; an old sender is outside the window
    rows = [tx(1, "BHOT", "HOT", 500, 5), tx(2, "OLD", "HOT", 5, -60),
            *deposit_and_sweep(3, "D1", "HOT", 10)]
    result, chain = run(rows)
    assert sorted(by_address(result)) == ["D1"]
    assert result.stats["ExA"]["labelled_senders"] == 1
    as_candidate = {c[0] for c in chain.calls if c[1] == "both"}
    assert as_candidate == {"D1"}


def test_candidate_history_reaches_back_before_the_window():
    # the deposit came 2 days before the window, the sweep inside it
    rows = [tx(1, "U1", "D1", 100, -2 * 24 * 60), tx(2, "D1", "HOT", 100, 5)]
    result, _ = run(rows, rules=DiscoverConfig(max_hours=72))
    assert by_address(result)["D1"].status == "derived"
    result, _ = run(rows, rules=DiscoverConfig(max_hours=72), lookback_days=1)
    assert by_address(result) == {}


def test_a_sender_that_fails_the_sweep_rule_is_counted_with_the_reason_and_costs_no_gas_call():
    rows = [tx(1, "U1", "W", 1000, 0), tx(2, "W", "HOT", 10, 5),
            *deposit_and_sweep(3, "D1", "HOT", 10)]
    result, chain = run(rows)
    assert sorted(by_address(result)) == ["D1"]
    s = result.stats["ExA"]
    assert s["candidates"] == 2 and s["fired"] == 1 and s["derived"] == 1
    assert s["rejected"] == {"forwards under 90% of what it receives": 1}
    assert chain.gas_calls == ["D1"]


def test_a_gas_conflict_is_recorded_and_is_not_a_derived_label():
    result, _ = run(deposit_and_sweep(1, "D1", "HOT", 0), gas={"D1": [ev("BHOT", 4)]})
    d1 = by_address(result)["D1"]
    assert d1.status == "conflict" and d1.confidence is None
    assert d1.conflict == "the rules name different exchanges"
    assert d1.gas_payer_entity == "ExB"
    assert result.stats["ExA"]["conflict"] == 1 and result.stats["ExA"]["derived"] == 0


def test_an_address_already_labelled_otherwise_is_a_conflict():
    result, _ = run(deposit_and_sweep(1, "BAD", "HOT", 0))
    bad = by_address(result)["BAD"]
    assert bad.status == "conflict"
    assert bad.conflict == "already labelled Lazarus (sanctioned, curated)"


def test_an_address_already_tagged_for_the_same_exchange_is_known():
    result, _ = run(deposit_and_sweep(1, "TAGGED", "HOT", 0))
    assert by_address(result)["TAGGED"].status == "known"
    assert result.stats["ExA"]["known"] == 1


def test_an_unlabelled_payer_serving_many_deposit_addresses_is_a_gas_station():
    rows, gas = [], {}
    for i in range(10):
        rows += deposit_and_sweep(10 * i + 1, f"D{i}", "HOT", i)
        gas[f"D{i}"] = [ev("STATION", i + 4)]
    rows += deposit_and_sweep(500, "LONE", "HOT", 50)
    gas["LONE"] = [ev("SOMEONE", 54)]
    result, _ = run(rows, gas)
    f = by_address(result)
    assert all(f[f"D{i}"].rule == "sweep+station" for i in range(10))
    assert f["D0"].confidence == 0.765 and f["D0"].gas_payer == "STATION"
    assert f["D0"].gas_verdict == "station" and f["D0"].gas_payer_entity == "ExA"
    assert "derived as a ExA gas station" in f["D0"].evidence
    assert (f["LONE"].rule, f["LONE"].gas_verdict) == ("sweep", "unlabelled")
    assert result.stations == [{"address": "STATION", "chain": CHAIN, "entity": "ExA",
                                "addresses": 10, "share": 1.0, "kinds": "energy"}]


def test_a_payer_serving_two_exchanges_is_not_a_station():
    rows, gas = [], {}
    for i in range(10):
        hot = "HOT" if i < 6 else "BHOT"
        rows += deposit_and_sweep(10 * i + 1, f"D{i}", hot, i)
        gas[f"D{i}"] = [ev("RENTAL", i + 4)]
    result, _ = run(rows, gas)
    assert result.stations == []
    assert {f.rule for f in result.findings} == {"sweep"}


def test_another_exchanges_station_is_a_conflict():
    rows, gas = [], {}
    for i in range(20):
        rows += deposit_and_sweep(10 * i + 1, f"D{i}", "HOT", i)
        gas[f"D{i}"] = [ev("STATION", i + 4)]
    rows += deposit_and_sweep(900, "ODD", "BHOT", 50)
    gas["ODD"] = [ev("STATION", 54)]
    result, _ = run(rows, gas)
    odd = by_address(result)["ODD"]
    assert odd.status == "conflict" and odd.gas_payer_entity == "ExA"


def test_candidates_per_seed_can_be_capped_in_order_of_first_appearance():
    rows = (deposit_and_sweep(1, "D1", "HOT", 0) + deposit_and_sweep(3, "D2", "HOT", 10)
            + deposit_and_sweep(5, "D3", "HOT", 20))
    result, _ = run(rows, max_candidates=2)
    assert sorted(by_address(result)) == ["D1", "D2"]


def test_only_the_chosen_exchanges_are_crawled():
    rows = deposit_and_sweep(1, "D1", "HOT", 0) + deposit_and_sweep(3, "E1", "BHOT", 10)
    result, _ = run(rows, entities=("ExB",))
    assert sorted(by_address(result)) == ["E1"] and list(result.stats) == ["ExB"]


def test_a_failed_fetch_is_counted_and_the_crawl_goes_on():
    rows = deposit_and_sweep(1, "D1", "HOT", 0) + deposit_and_sweep(3, "D2", "HOT", 10)
    result, _ = run(rows, fail=("D1",))
    assert sorted(by_address(result)) == ["D2"]
    assert result.stats["ExA"]["errors"] == 1


def test_stats_per_exchange_and_totals():
    rows = deposit_and_sweep(1, "D1", "HOT", 0) + deposit_and_sweep(3, "E1", "BHOT", 10)
    result, _ = run(rows, gas={"D1": [ev("GASA", 4)]})
    a = result.stats["ExA"]
    assert (a["seeds"], a["active_seeds"], a["inbound_rows"], a["candidates"]) == (2, 1, 1, 1)
    assert a["by_rule"] == {"sweep+gas": 1}
    assert result.stats["ExB"]["by_rule"] == {"sweep": 1}
    assert result.totals["derived"] == 2 and result.totals["candidates"] == 2


def test_the_result_is_the_same_on_every_run():
    rows = deposit_and_sweep(1, "D2", "HOT", 0) + deposit_and_sweep(3, "D1", "BHOT", 10)
    one, _ = run(rows)
    two, _ = run(list(reversed(rows)))
    assert one.findings == two.findings
    assert [f.address for f in one.findings] == ["D2", "D1"]      # by exchange, then address


def test_a_failed_gas_listing_is_counted_too():
    class Broken(Chain):
        def gas_events(self, address, since=None, limit=None):
            raise ProviderError("gas listing failed")
    chain = Broken(deposit_and_sweep(1, "D1", "HOT", 0))
    result = discover(CHAIN, chain, chain, Labels(LABELS), CrawlConfig(window_start=T0))
    assert result.findings == [] and result.stats["ExA"]["errors"] == 1
