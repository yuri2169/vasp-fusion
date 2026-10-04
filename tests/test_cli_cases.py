"""`cli trace` and `cli demo`, run offline against a cache filled from the recorded demo
wallets: what `OFFLINE=1 make demo` does on a prepared machine."""
import json

import pytest

from demokit import SPECS, demo_label_db, run_demo
from vaspfusion import cli
from vaspfusion.store.cases import CaseStore

COINDCX = SPECS["tron-coindcx"]["address"]


@pytest.fixture
def offline(tmp_path, monkeypatch):
    """A machine with a filled chain cache, a label DB, no network and no keys."""
    cache = tmp_path / "chain_cache.duckdb"
    for case_id in SPECS:
        run_demo(case_id, cache)                       # replay the recordings into the cache
    monkeypatch.setenv("VASPFUSION_CHAIN_CACHE", str(cache))
    monkeypatch.setenv("VASPFUSION_CASE_DB", str(tmp_path / "case.duckdb"))
    monkeypatch.setenv("OFFLINE", "1")
    monkeypatch.setenv("ETHERSCAN_API_KEY", "offline")   # any value: selects the cached backend
    monkeypatch.setenv("TRONGRID_API_KEY", "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")
    return ["--labels-db", str(demo_label_db(tmp_path / "labels.duckdb"))]


def test_trace_prints_the_case_for_an_officer(offline, capsys):
    cli.main(["trace", COINDCX, *offline])
    out = capsys.readouterr().out
    assert "ATTRIBUTED" in out and "CoinDCX" in out
    # the deposit address was confirmed by the model: its value, with a range, not the
    # rules' 0.81
    assert "CoinDCX  confidence 0.85 (range narrower than 0.01)" in out
    assert "rule confidence" not in out.splitlines()[0]
    assert "58%" in out and "hub" in out
    assert "Draft a request to CoinDCX" in out
    assert "0 live" in out and "OFFLINE=1" in out


def test_trace_json_is_the_case_detail(offline, capsys):
    cli.main(["trace", COINDCX, "--json", *offline])
    case = json.loads(capsys.readouterr().out)
    assert (case["outcome"], case["top_vasp"]) == ("ATTRIBUTED", "CoinDCX")
    assert case["provenance"]["offline_replay"] is True


def test_trace_of_an_uncached_wallet_offline_exits_with_the_reason(offline, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["trace", "TGjpmhAFT6d7eBKvaFwPVN6H2pDKgLLZiw", *offline])
    assert e.value.code == 1
    assert "OFFLINE=1 and not cached" in capsys.readouterr().err


def test_demo_runs_every_wallet_and_stores_the_cases(offline, tmp_path, capsys):
    cli.main(["demo", *offline])
    out = capsys.readouterr().out
    for case_id, spec in SPECS.items():
        assert case_id in out and spec["expect"]["outcome"] in out
    assert f"{len(SPECS)}/{len(SPECS)} as expected" in out
    stored = CaseStore(tmp_path / "case.duckdb").list()
    assert {c["id"] for c in stored} == set(SPECS)
    assert all(c["demo"] and c["status"] == "done" for c in stored)
    assert {c["case_ref"] for c in stored} == {s["case_ref"] for s in SPECS.values()}


def test_demo_fails_loudly_when_a_wallet_no_longer_attributes_as_expected(offline, tmp_path, capsys):
    doc = {"cases": [{**SPECS["tron-coindcx"], "expect": {"outcome": "ATTRIBUTED",
                                                           "top_vasp": "OKX"}}]}
    wrong = tmp_path / "cases.json"
    wrong.write_text(json.dumps(doc))
    with pytest.raises(SystemExit) as e:
        cli.main(["demo", "--file", str(wrong), *offline])
    assert e.value.code == 1
    assert "expected ATTRIBUTED / OKX" in capsys.readouterr().out


def test_demo_still_seeds_the_watchlist_when_a_watched_wallet_cannot_be_traced(offline, capsys):
    """This cache holds the demo cases' pages only: the two wallets traced for the watchlist
    are not in it. They are watched all the same, with no first check."""
    from vaspfusion.store.watch import WatchStore
    cli.main(["demo", *offline])
    out = capsys.readouterr().out
    assert "could not be traced for its first check" in out and "5 wallets on the watchlist" in out
    untraced = [e for e in WatchStore().list() if e["baseline"] is None]
    assert len(untraced) == 2
