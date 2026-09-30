"""The label DB builder, run on real rows copied verbatim into tests/fixtures."""
import hashlib

import duckdb

from vaspfusion.labels.load import LABEL_COLUMNS, build_labels

from pathlib import Path

FIX = Path(__file__).parent.parent / "fixtures" / "labels"


def _rows(db):
    with duckdb.connect(str(db), read_only=True) as con:
        return con.execute(f"SELECT {', '.join(LABEL_COLUMNS)} FROM labels "
                           "ORDER BY chain, address").fetchall()


def _one(db, address, chain):
    with duckdb.connect(str(db), read_only=True) as con:
        cur = con.execute(f"SELECT {', '.join(LABEL_COLUMNS)} FROM labels "
                          "WHERE address = ? AND chain = ?", [address, chain])
        row = cur.fetchone()
    return dict(zip(LABEL_COLUMNS, row)) if row else None


def test_all_csv_is_skipped_and_duplicates_collapse(fixture_db):
    db, stats = fixture_db
    # 11 wallet-attribution rows + 4 Dune rows, one address in both sources.
    assert stats["raw_rows"] == 15
    assert stats["duplicates_dropped"] == 1
    assert stats["total"] == 14 == len(_rows(db))


def test_highest_tier_wins_a_duplicate(fixture_db):
    db, _ = fixture_db
    row = _one(db, "12T8i8tpeczk5JGf8ppZf1w6SFBRwEa9y4", "bitcoin")
    assert row["tier"] == "published_por"
    assert row["source"] == "defillama-cex"
    assert row["entity"] == "CoinDCX"


def test_evm_address_is_stored_lowercase(fixture_db):
    db, _ = fixture_db
    row = _one(db, "0x0639556f03714a74a5feeaf5736a4a64ff70d206", "cronos")
    assert row["entity"] == "Bitget"
    assert _one(db, "0x0639556F03714A74a5fEEaF5736a4A64fF70D206", "cronos") is None


def test_tron_address_keeps_case_and_dune_chain_is_mapped(fixture_db):
    db, _ = fixture_db
    row = _one(db, "TAWK8YMnn7yAfnQRyvjiBv9ksocFt9qNdR", "tron")
    assert row["entity"] == "CoinDCX"
    assert row["tier"] == "curated"
    assert row["source_url"].startswith("https://github.com/duneanalytics/spellbook")


def test_quoted_comma_in_label_survives(fixture_db):
    db, _ = fixture_db
    row = _one(db, "0x03893a7c7463ae47d46bc7f091665f1893656003", "ethereum")
    assert row["label"] == "Tornado.Cash: 50,000 cDAI 2"
    assert row["category"] == "mixer"
    assert row["entity"] == "Tornado.Cash"


def test_stats_count_vasp_categories(fixture_db):
    _, stats = fixture_db
    assert stats["by_category"]["swap_service"] == 1
    assert stats["by_category"]["custodial_wallet"] == 1
    assert stats["by_category"]["entity"] == 1          # the Vela token contract
    assert stats["by_chain"]["evm"] == 2
    assert stats["by_tier"]["published_por"] == 3


def test_exchange_tag_promotion_is_counted(fixture_db):
    db, stats = fixture_db
    row = _one(db, "0x46c503f0a14975d2e1d84135bba2b20270da2851", "avalanche")
    assert (row["entity"], row["category"], row["kind"]) == ("OKX", "exchange", "deposit")
    assert stats["exchange_tag_promoted"] == 1


def test_rebuild_is_deterministic(fixture_db, tmp_path):
    db, _ = fixture_db
    again = tmp_path / "again.duckdb"
    build_labels(again, FIX / "wa", FIX / "dune.csv")
    build_labels(again, FIX / "wa", FIX / "dune.csv")  # overwrite in place
    digest = lambda p: hashlib.sha256(repr(_rows(p)).encode()).hexdigest()
    assert digest(again) == digest(db)
