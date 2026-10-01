"""A small real crawl (CoinDCX and KuCoin on Tron, 24 Sep 2026), replayed from recorded
TronGrid responses and the real label rows. No network."""
from dataclasses import asdict

import pytest

from discoverkit import FixtureLabels, load, replay_fetcher
from vaspfusion.chains.tron import TronProvider
from vaspfusion.discover.crawl import CrawlConfig, discover

CFG = CrawlConfig(seed_limit=200, max_candidates=5, entities=("CoinDCX", "KuCoin"))
COINDCX_2 = "TU7BbAsb8t371eMijQeiGXsiLvY1vZbsFs"
COINDCX_10 = "TFLxNHunhEizmeEdiMyA3r2XGLSKaEznGd"
KUCOIN_HOT = "TUpHuDkiCCmwaTZBHZvQdwWzGNm5t8J2b9"


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch, tmp_path):
    monkeypatch.delenv("OFFLINE", raising=False)
    monkeypatch.setenv("TRONGRID_API_KEY", "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")


def crawl(tmp_path, offline=False):
    fetcher = replay_fetcher(tmp_path, "crawl_tron", offline=offline)
    result = discover("tron", TronProvider(fetcher, page_size=200, max_pages=1),
                      TronProvider(fetcher, page_size=50, max_pages=1),
                      FixtureLabels("crawl_tron"), CFG)
    return result, fetcher


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("crawl")
    mp.delenv("OFFLINE", raising=False)
    mp.setenv("TRONGRID_API_KEY", "")
    mp.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp / "no.env")
    try:
        yield crawl(tmp)[0]
    finally:
        mp.undo()


def test_ten_real_deposit_addresses_are_derived_with_both_rules(result):
    assert [(f.entity, f.status, f.rule) for f in result.findings] == \
        [("CoinDCX", "derived", "sweep+gas")] * 5 + [("KuCoin", "derived", "sweep+gas")] * 5
    assert result.totals["derived"] == 10 and result.totals["conflict"] == 0


def test_a_coindcx_deposit_address_and_its_evidence(result):
    f = next(f for f in result.findings if f.address == "TTTZH6nWX8tk1b73xHfCJk3x9aBRgWbeEK")
    assert (f.sweep_target, f.target_tier, f.asset, f.share) == (COINDCX_2, "curated", "USDT", 1.0)
    assert (f.gas_verdict, f.gas_payer, f.gas_payer_entity, f.gas_kinds) == \
        ("confirmed", COINDCX_10, "CoinDCX", "native")
    assert f.confidence == 0.8075 and f.category == "exchange" and f.kind == "deposit"
    assert f.evidence == (
        "Sweep rule: forwarded 100% of the 186.54 USDT it received from 2 senders to CoinDCX "
        "wallet TU7BbA…vZbsFs (curated list) in 2 sweeps, typically 48 seconds after arrival. "
        "Gas rule: TFLxNH…aEznGd, labelled CoinDCX, sent the fee money for 1 of 2 sweeps. "
        "Both rules agree. Rule confidence 0.81, not calibrated.")


def test_kucoin_deposit_addresses_weigh_more_because_the_seed_is_proof_of_reserves(result):
    kucoin = [f for f in result.findings if f.entity == "KuCoin"]
    assert {f.sweep_target for f in kucoin} == {KUCOIN_HOT}
    assert {f.target_tier for f in kucoin} == {"published_por"}
    assert {f.confidence for f in kucoin} == {0.9025}
    # KuCoin both tops up TRX and delegates energy, from two of its published wallets
    assert {(f.gas_verdict, f.gas_payer_entity) for f in kucoin} == {("confirmed", "KuCoin")}
    assert {f.gas_kinds for f in kucoin} <= {"native", "energy"}


def test_the_replay_reproduces_what_was_recorded(result):
    expected = load("crawl_tron")["expected"]
    assert [asdict(f) for f in result.findings] == expected["findings"]
    assert result.stats == expected["stats"] and result.totals == expected["totals"]


def test_a_second_run_is_served_from_the_cache_and_is_identical(tmp_path):
    first, fetcher = crawl(tmp_path)
    assert fetcher.transport.calls == fetcher.stats["live"] > 0
    again, offline = crawl(tmp_path, offline=True)
    assert again.findings == first.findings and again.stats == first.stats
    assert offline.transport.calls == 0 and offline.stats["live"] == 0


def test_stats_name_the_wallets_that_were_already_labelled(result):
    assert result.stats["CoinDCX"]["seeds"] == 13 and result.stats["CoinDCX"]["active_seeds"] == 1
    assert result.stats["KuCoin"]["seeds"] == 24
    assert result.stats["KuCoin"]["labelled_senders"] >= 1      # KuCoin moving between its own
