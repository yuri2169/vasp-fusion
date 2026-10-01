"""Derived rows in the label DB: the real replayed crawl (10 CoinDCX and KuCoin deposit
addresses) merged into the fixture label DB."""
from dataclasses import replace
from pathlib import Path

import duckdb
import pytest

from test_discover_real import crawl
from vaspfusion.discover.crawl import DiscoveryResult
from vaspfusion.discover.store import write_result
from vaspfusion.labels.load import build_labels
from vaspfusion.labels.lookup import LabelStore

FIX = Path(__file__).parent / "fixtures" / "labels"
DEP = "TTTZH6nWX8tk1b73xHfCJk3x9aBRgWbeEK"            # derived CoinDCX deposit address
CURATED = "TAWK8YMnn7yAfnQRyvjiBv9ksocFt9qNdR"        # "CoinDCX 11" in the Dune list


@pytest.fixture(scope="module")
def findings(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("crawl")
    mp.delenv("OFFLINE", raising=False)
    mp.setenv("TRONGRID_API_KEY", "")
    mp.setattr("vaspfusion.chains.http.DEFAULT_ENV", tmp / "no.env")
    try:
        return crawl(tmp)[0].findings
    finally:
        mp.undo()


def build(tmp_path, findings):
    write_result(tmp_path / "derived", DiscoveryResult("tron", {}, findings))
    db = tmp_path / "labels.duckdb"
    return db, build_labels(db, FIX / "wa", FIX / "dune.csv", derived_dir=tmp_path / "derived")


def test_derived_rows_become_labels_with_evidence_and_a_confidence(tmp_path, findings):
    db, stats = build(tmp_path, findings)
    assert stats["derived_loaded"] == 10 and stats["by_tier"]["derived"] == 10
    with LabelStore(db) as store:
        hit = store.lookup(DEP, "tron")
    assert (hit.entity, hit.category, hit.kind, hit.tier) == \
        ("CoinDCX", "exchange", "deposit", "derived")
    assert hit.source == "vaspfusion-discover" and hit.source_url is None
    assert hit.label == "CoinDCX deposit address (derived: sweep + gas payer)"
    assert hit.confidence == 0.8075
    assert hit.evidence.startswith("Sweep rule: forwarded 100% of the 186.54 USDT")
    assert hit.is_vasp


def test_other_labels_have_no_confidence_or_evidence(tmp_path, findings):
    db, _ = build(tmp_path, findings)
    with LabelStore(db) as store:
        hit = store.lookup(CURATED, "tron")
    assert hit.tier == "curated" and hit.confidence is None and hit.evidence is None


def test_conflicts_and_known_addresses_are_not_labels(tmp_path, findings):
    changed = [replace(findings[0], status="conflict", confidence=None,
                       conflict="the rules name different exchanges"),
               replace(findings[1], status="known", confidence=None), *findings[2:]]
    db, stats = build(tmp_path, changed)
    assert stats["derived_loaded"] == 8
    with LabelStore(db) as store:
        assert store.lookup(findings[0].address, "tron") is None
        assert store.lookup(findings[1].address, "tron") is None


def test_a_derived_row_never_replaces_a_label_of_a_higher_tier(tmp_path, findings):
    clash = replace(findings[0], address=CURATED, entity="KuCoin")
    db, stats = build(tmp_path, [clash, *findings[1:]])
    with LabelStore(db) as store:
        hit = store.lookup(CURATED, "tron")
    assert (hit.entity, hit.tier) == ("CoinDCX", "curated")
    assert stats["by_tier"]["derived"] == 9 and stats["derived_loaded"] == 10


def test_derived_labels_are_not_seeds(tmp_path, findings):
    db, _ = build(tmp_path, findings)
    with LabelStore(db) as store:
        assert DEP not in {l.address for l in store.seeds("tron")}


def test_without_a_derived_folder_nothing_changes(tmp_path):
    db = tmp_path / "labels.duckdb"
    stats = build_labels(db, FIX / "wa", FIX / "dune.csv", derived_dir=tmp_path / "missing")
    assert stats["derived_loaded"] == 0 and "derived" not in stats["by_tier"]
    assert stats["total"] == 15


def test_a_rebuild_gives_the_same_rows(tmp_path, findings):
    def rows(db):
        with duckdb.connect(str(db), read_only=True) as con:
            return con.execute("SELECT * FROM labels ORDER BY chain, address").fetchall()
    a, _ = build(tmp_path / "a", findings)
    b, _ = build(tmp_path / "b", list(reversed(findings)))
    assert rows(a) == rows(b)


def test_a_label_db_built_before_b4_is_still_readable(tmp_path):
    db = tmp_path / "old.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE TABLE labels (address VARCHAR, chain VARCHAR, entity VARCHAR, "
                    "category VARCHAR, kind VARCHAR, tier VARCHAR, source VARCHAR, "
                    "source_url VARCHAR, label VARCHAR, PRIMARY KEY (address, chain))")
        con.execute("INSERT INTO labels VALUES (?, 'tron', 'CoinDCX', 'exchange', 'unknown', "
                    "'curated', 'dune-spellbook', NULL, 'CoinDCX 11')", [CURATED])
    with LabelStore(db) as store:
        hit = store.lookup(CURATED, "tron")
        assert hit.entity == "CoinDCX" and hit.confidence is None
        assert store.lookup_many([(CURATED, "tron")])[(CURATED, "tron")] == hit
        assert store.search("CoinDCX")[1] == [hit] and store.seeds("tron") == [hit]
