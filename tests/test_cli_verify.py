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
    # every request in it is one a demo receipt lists (a receipt lists each request once),
    # or one recorded for a watchlist wallet's first check
    fix = Path(__file__).parent / "fixtures" / "demo"
    watched = sum(len(json.loads((fix / f"{t['id']}.json").read_text())["responses"])
                  for t in cli.watch_traces(fix.parents[2] / "demo" / "watchlist.json"))
    assert 0 < requests <= sum(g["pages"] for g in golden.values()) + watched
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
    # the eight demo cases, and the two wallets traced for the demonstration watchlist
    stored = len(SPECS) + len(cli.watch_traces(Path(__file__).resolve().parents[1] / "demo" / "watchlist.json"))
    assert out.count("VERIFIED") == stored and "NOT VERIFIED" not in out
    assert f"{stored}/{stored} verified" in out


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


# ---- the demonstration watchlist (demo/watchlist.json)
WATCH = json.loads((Path(__file__).resolve().parents[1] / "demo" / "watchlist.json").read_text())["watch"]


def test_the_watchlist_wallets_are_ones_the_demo_cases_reached():
    from vaspfusion.store.watch import watch_id
    assert len(WATCH) == 5 and len({watch_id(w["chain"], w["address"]) for w in WATCH}) == 5
    for w in WATCH:
        responses = (Path(__file__).parent / "fixtures" / "demo" / f"{w['seen_in']}.json").read_text()
        assert w["seen_in"] in SPECS and w["address"] in responses, w["address"]
        assert w["note"].strip()


def test_the_demo_seeds_the_watchlist_once_each_with_a_real_first_check(machine, tmp_path,
                                                                        monkeypatch, capsys):
    from vaspfusion.store.watch import WatchStore
    monkeypatch.setenv("VASPFUSION_WATCH_DB", str(tmp_path / "watch.duckdb"))
    assert WatchStore().list() == []                 # nothing is watched before demo set-up
    cli.main(["demo", *machine])
    assert "5 wallets on the watchlist (5 added)" in capsys.readouterr().out
    entries = {e["address"]: e for e in WatchStore().list()}
    assert set(entries) == {w["address"] for w in WATCH}
    cases = CaseStore()
    for w in WATCH:
        e = entries[w["address"]]
        case = cases.find(w["chain"], w["address"])
        assert e["note"] == w["note"]
        # the first check is the wallet's own finished trace, at the time it was traced
        assert e["baseline"]["case_id"] == case["id"]
        assert e["baseline"]["traced_at"] == (case["provenance"]["fetched_at"] or case["created_at"])
        if "trace" in w:                             # traced for the watchlist: not a demo case
            assert case["id"] == w["trace"]["id"] and not case["demo"]
    cli.main(["demo", *machine])                     # set up again: nothing is added twice
    assert "5 wallets on the watchlist (0 added)" in capsys.readouterr().out
    again = {e["address"]: e for e in WatchStore().list()}
    assert {a: e["added_at"] for a, e in again.items()} == {a: e["added_at"] for a, e in entries.items()}


# ------------------------------------------------------------------ a clone without the label sets
def test_demo_labels_builds_the_database_the_recorded_demo_needs(tmp_path, capsys):
    db = tmp_path / "labels.duckdb"
    cli.main(["demo-labels", "--db", str(db)])
    said = capsys.readouterr().out
    assert "27 labels" in said and "NOT the full label database" in said
    from vaspfusion.labels.lookup import LabelStore
    with LabelStore(db) as store:       # a real label store: the CoinDCX wallet is in it
        got = store.lookup_many([("TU7BbAsb8t371eMijQeiGXsiLvY1vZbsFs", "tron")])
    assert [lab.entity for lab in got.values()] == ["CoinDCX"]


def test_demo_labels_never_replaces_a_database_that_is_there(tmp_path, capsys):
    db = tmp_path / "labels.duckdb"
    db.write_bytes(b"the full label database")
    cli.main(["demo-labels", "--db", str(db)])
    assert db.read_bytes() == b"the full label database"
    assert "left alone" in capsys.readouterr().out
    cli.main(["demo-labels", "--db", str(db), "--force"])
    assert db.read_bytes() != b"the full label database"


def test_labels_without_the_label_sets_says_what_is_missing_and_what_to_do(tmp_path, capsys):
    with pytest.raises(SystemExit) as stop:
        cli.main(["labels", "--research", str(tmp_path / "nowhere"),
                  "--db", str(tmp_path / "labels.duckdb")])
    assert stop.value.code == 1
    said = capsys.readouterr().err
    assert "wallet-attribution" in said and "indian_vasps_dune_spellbook.csv" in said
    assert "make demo-labels" in said and "RESEARCH=" in said
    assert not (tmp_path / "labels.duckdb").exists()
