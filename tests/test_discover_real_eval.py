"""The hold-out test on 12 real Etherscan-tagged addresses (6 Bitget deposit addresses,
6 that are not deposit addresses), replayed from recorded Etherscan responses."""
import pytest

from discoverkit import FixtureLabels, load, replay_fetcher
from vaspfusion.chains.evm import EvmProvider
from vaspfusion.discover.evaluate import EvalConfig, evaluate

CFG = EvalConfig(n_positive=6, n_negative=6, limit=50)


@pytest.fixture(autouse=True)
def _no_live(monkeypatch, tmp_path):
    monkeypatch.delenv("OFFLINE", raising=False)
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")


def run(tmp_path, offline=False):
    fix = load("holdout_eth")
    fetcher = replay_fetcher(tmp_path, "holdout_eth", offline=offline)
    # any non-empty key selects the Etherscan backend the fixture was recorded from
    provider = EvmProvider("ethereum", fetcher, page_size=CFG.limit, max_pages=1, key="test-key")
    g = fix["groups"]
    report = evaluate(provider, FixtureLabels("holdout_eth"), g["positives"],
                      g["neg_exchange"], g["neg_other"], CFG)
    return report, fetcher, fix


def test_two_of_six_tagged_bitget_deposit_addresses_are_rediscovered(tmp_path):
    report, _, _ = run(tmp_path)
    m = report.metrics
    assert (m["positives"], m["true_positives"], m["wrong_entity"]) == (6, 2, 0)
    assert m["recall"] == 0.3333 and m["entity_precision"] == 1.0
    # the other four never held a stablecoin in their first 50 transfers
    assert m["missed_by_reason"] == {"no stablecoin transfers": 4}
    assert m["positives_with_stablecoin_activity"] == 2
    assert m["recall_with_stablecoin_activity"] == 1.0


def test_the_one_false_positive_is_an_exchange_wallet_and_names_its_own_exchange(tmp_path):
    report, _, _ = run(tmp_path)
    m = report.metrics
    assert m["negatives"] == 6 and m["false_positives"] == 1
    assert m["false_positives_naming_the_tagged_exchange"] == 1
    fp = next(r for r in report.rows if r["outcome"] == "false_positive")
    assert (fp["truth"], fp["tag"], fp["entity"]) == ("exchange_wallet", "Deribit", "Deribit")
    assert m["false_positive_rate"] == {"exchange_wallets": 0.3333, "other_tagged": 0.0}


def test_the_replay_reproduces_what_was_recorded_and_runs_offline(tmp_path):
    report, fetcher, fix = run(tmp_path)
    assert report.metrics == fix["expected"]["metrics"]
    assert report.rows == fix["expected"]["rows"]
    assert fetcher.transport.calls > 0
    again, offline, _ = run(tmp_path, offline=True)
    assert again.rows == report.rows and offline.transport.calls == 0
