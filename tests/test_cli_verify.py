"""`cli demo-cache`, `cli demo --golden` and `cli verify`: what the offline image does
at build time. Everything is read from the recorded demo fixtures; no network."""
import json
from pathlib import Path

import pytest

from demokit import SPECS, demo_label_db
from vaspfusion import cli
from vaspfusion.chains.cache import ChainCache
from vaspfusion.store.cases import CaseStore

GOLDEN = Path(__file__).parent / "golden" / "fingerprints.json"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """`demo-cache` run once: (cache file, label DB file)."""
    d = tmp_path_factory.mktemp("demo-cache")
    labels = demo_label_db(d / "labels.duckdb")
    cli.main(["demo-cache", "--out", str(d / "demo_cache.duckdb"), "--labels-db", str(labels)])
    return d / "demo_cache.duckdb", labels


@pytest.fixture
def machine(built, tmp_path, monkeypatch):
    """A machine holding only that cache and label DB: no network, no keys."""
    cache, labels = built
    monkeypatch.setenv("VASPFUSION_CHAIN_CACHE", str(cache))
    monkeypatch.setenv("VASPFUSION_CASE_DB", str(tmp_path / "case.duckdb"))
    monkeypatch.setenv("OFFLINE", "1")
    monkeypatch.setenv("ETHERSCAN_API_KEY", "offline")
    monkeypatch.setenv("TRONGRID_API_KEY", "")
    monkeypatch.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp_path / "no.env")
    return ["--labels-db", str(labels)]


def test_demo_cache_holds_every_page_the_demo_reads_and_nothing_else(built, capsys):
    cache, _ = built
    golden = json.loads(GOLDEN.read_text())
    import duckdb
    con = duckdb.connect(str(cache), read_only=True)
    requests = con.execute("SELECT count(DISTINCT query) FROM chain_cache").fetchone()[0]
    con.close()
    # every request in it is one a demo receipt lists (a receipt lists each request once)
    assert 0 < requests <= sum(g["pages"] for g in golden.values())
    assert ChainCache(cache).count() >= requests


def test_the_demo_runs_offline_from_it_and_matches_the_golden_fingerprints(machine, capsys):
    cli.main(["demo", "--golden", str(GOLDEN), *machine])
    out = capsys.readouterr().out
    assert f"{len(SPECS)}/{len(SPECS)} as expected" in out
    assert f"{len(SPECS)}/{len(SPECS)} golden fingerprints reproduced" in out
    assert " 0 live" in out


def test_a_wrong_golden_fingerprint_fails_the_demo(machine, tmp_path, capsys):
    golden = json.loads(GOLDEN.read_text())
    golden["tron-coindcx"]["findings_sha256"] = "0" * 64
    wrong = tmp_path / "golden.json"
    wrong.write_text(json.dumps(golden))
    with pytest.raises(SystemExit) as e:
        cli.main(["demo", "--golden", str(wrong), *machine])
    assert e.value.code == 1
    assert "tron-coindcx" in capsys.readouterr().out


def test_verify_all_passes_on_the_stored_demo_cases(machine, capsys):
    cli.main(["demo", *machine])
    capsys.readouterr()
    cli.main(["verify", "--all", *machine])
    out = capsys.readouterr().out
    assert out.count("VERIFIED") == len(SPECS) and "NOT VERIFIED" not in out
    assert f"{len(SPECS)}/{len(SPECS)} verified" in out


def test_verify_one_case_prints_each_check(machine, capsys):
    cli.main(["demo", *machine])
    capsys.readouterr()
    cli.main(["verify", "tron-coindcx", *machine])
    out = capsys.readouterr().out
    assert "tron-coindcx" in out and "VERIFIED" in out
    for name in ("stored_case", "responses", "findings", "labels", "model"):
        assert name in out


def test_verify_exits_1_when_a_stored_case_was_edited(machine, tmp_path, capsys):
    cli.main(["demo", *machine])
    store = CaseStore(tmp_path / "case.duckdb")
    case = store.get("eth-bitget")
    case["confidence"] = case["candidates"][0]["confidence"] = 0.99
    store.save(case)
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        cli.main(["verify", "--all", "--json", *machine])
    assert e.value.code == 1
    results = {r["case_id"]: r for r in json.loads(capsys.readouterr().out)}
    assert results["eth-bitget"]["matches"] is False
    assert results["tron-coindcx"]["matches"] is True


def test_verify_an_unknown_case_exits_with_the_reason(machine, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["verify", "nope", *machine])
    assert e.value.code == 1 and "no case nope" in capsys.readouterr().err


def test_a_receipt_file_verifies_without_the_case_store(machine, tmp_path, capsys):
    cli.main(["demo", *machine])
    from vaspfusion.provenance import receipt
    path = tmp_path / "tron-ofac.receipt.json"
    path.write_text(json.dumps(receipt(CaseStore(tmp_path / "case.duckdb").get("tron-ofac"))))
    capsys.readouterr()
    cli.main(["verify", "--receipt", str(path), *machine])
    assert "VERIFIED" in capsys.readouterr().out


def test_demo_cache_refuses_a_request_the_fixtures_do_not_hold(built, tmp_path, capsys):
    """A fixture one page short: the build stops instead of shipping a cache with a hole."""
    from demokit import FIX
    _, labels = built
    full = json.loads((FIX / "tron-ofac.json").read_text())
    last = sorted(full["responses"])[-1]
    del full["responses"][last]
    (tmp_path / "tron-ofac.json").write_text(json.dumps(full))
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": [SPECS["tron-ofac"]]}))
    with pytest.raises(SystemExit) as e:
        cli.main(["demo-cache", "--file", str(cases), "--fixtures", str(tmp_path),
                  "--out", str(tmp_path / "c.duckdb"), "--labels-db", str(labels)])
    assert e.value.code == 1
    assert "not in the recorded fixtures" in capsys.readouterr().err
    assert not (tmp_path / "c.duckdb").exists()
    assert not (tmp_path / "c.duckdb.tmp").exists()
