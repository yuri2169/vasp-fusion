"""GraphSense TagPacks (exchange packs) as a label source. The packs under
tests/fixtures/labels/tagpacks are real excerpts: pack headers and tags copied verbatim."""
import csv
from pathlib import Path

import duckdb

from vaspfusion.labels.load import LABEL_COLUMNS, build_labels
from vaspfusion.labels.tagpacks import COLUMNS, read_packs, write_csv

FIX = Path(__file__).parent.parent / "fixtures" / "labels"
PACKS = FIX / "tagpacks"


def _by_address(rows):
    return {(r["address"], r["currency"]): r for r in rows}


def _db(tmp_path, wa="wa", packs=PACKS):
    out = tmp_path / "tagpacks.csv"
    write_csv(read_packs(packs), out)
    db = tmp_path / "labels.duckdb"
    stats = build_labels(db, FIX / wa, FIX / "dune.csv", tagpacks_csv=out)
    return db, stats


def _one(db, address, chain):
    with duckdb.connect(str(db), read_only=True) as con:
        row = con.execute(f"SELECT {', '.join(LABEL_COLUMNS)} FROM labels "
                          "WHERE address = ? AND chain = ?", [address, chain]).fetchone()
    return dict(zip(LABEL_COLUMNS, row)) if row else None


# ------------------------------------------------------------------ packs -> rows
def test_pack_level_fields_are_the_default_for_every_tag():
    rows = _by_address(read_packs(PACKS))
    okx = rows[("16rF2zwSJ9goQ9fZfYoti5LsUqqegb5RnA", "BTC")]
    assert okx["actor"] == "okex" and okx["label"] == "okx reserves wallets"
    assert okx["source_url"] == "https://twitter.com/okx/status/1590812545346330624"
    assert okx["source"] == "graphsense-tagpack:exchange-wallets-okx"
    assert okx["lastmod"] == "2022-11-15"
    # a tag's own field wins over the pack's
    assert rows[("0x5041ed759dd4afc3a72b8192c143f72f4724081a", "ETH")]["label"] == "okx ERC20 reserves"
    assert rows[("3BMEXbSSrK2K7cRgqxrtqUWfxowBBrW1BE", "BTC")]["actor"] == "bitmex"


def test_only_exchange_tags_on_traced_chains_are_kept():
    rows = read_packs(PACKS)
    assert {r["currency"] for r in rows} == {"BTC", "ETH", "TRX"}          # the DOGE tag is gone
    assert all(r["category"] == "exchange" for r in rows)
    assert not [r for r in rows if r["label"] == "HelixMixer"]             # a mixing service
    assert len(rows) == 16


def test_the_csv_is_sorted_and_the_same_on_a_rerun(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    write_csv(read_packs(PACKS), a)
    write_csv(list(reversed(read_packs(PACKS))), b)
    assert a.read_bytes() == b.read_bytes()
    with a.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0]) == COLUMNS
    assert [(r["source"], r["currency"], r["address"]) for r in rows] == \
        sorted((r["source"], r["currency"], r["address"]) for r in rows)


# ------------------------------------------------------------------ rows -> labels
def test_exchange_wallet_packs_load_as_curated_and_walletexplorer_as_explorer_tag(tmp_path):
    db, stats = _db(tmp_path)
    okx = _one(db, "16rF2zwSJ9goQ9fZfYoti5LsUqqegb5RnA", "bitcoin")
    assert (okx["entity"], okx["category"], okx["tier"], okx["kind"]) == \
        ("OKX", "exchange", "curated", "reserve")
    assert okx["source"] == "graphsense-tagpack:exchange-wallets-okx"
    assert okx["source_url"] == "https://twitter.com/okx/status/1590812545346330624"
    we = _one(db, "3Fh9p2W79ZHG54ettRJupkPTs23XcjrkT2", "bitcoin")
    assert (we["entity"], we["tier"], we["label"]) == ("Bitstamp", "explorer_tag", "Bitstamp.net")
    assert we["source_url"].startswith("https://www.walletexplorer.com/address/")
    assert stats["tagpack_rows"] == 16


def test_owner_names_match_the_rest_of_the_store(tmp_path):
    db, _ = _db(tmp_path)
    assert _one(db, "143gLvWYUojXaWZRrxquRKpVNTkhmr415B", "bitcoin")["entity"] == "HTX"
    assert _one(db, "1vdXJDiDSzeUAoM7eAcWZPhM9wEKmH8dG", "bitcoin")["entity"] == "HTX"
    assert _one(db, "3BMEXbSSrK2K7cRgqxrtqUWfxowBBrW1BE", "bitcoin")["entity"] == "BitMEX"
    assert _one(db, "bc1qpy4jwethqenp4r7hqls660wy8287vw0my32lmy", "bitcoin")["entity"] == "Crypto.com"
    assert _one(db, "3G3VG4X1WquWjqXT27JRwrRoyZgdyWf1dT", "bitcoin")["entity"] == "Kraken"
    assert _one(db, "3L1smrPn5chgVCehpUhvs5h5nJGxGQe6sD", "bitcoin")["entity"] == "Mercado Bitcoin"
    # a site the store has no name for keeps the name WalletExplorer gave it
    assert _one(db, "16xAAvXw4H2m2i1ASEeTAfg4sMVbWGBYkc", "bitcoin")["entity"] == "QuadrigaCX.com"
    assert _one(db, "1GwePtfuQKtV8YfUADi77RDVX5YKxNbFmp", "bitcoin")["entity"] == "CEX.IO"


def test_currencies_map_to_chains_and_evm_is_lowercased(tmp_path):
    db, _ = _db(tmp_path)
    assert _one(db, "TYh6mgoMNZTCsgpYHBz7gttEfrQmDMABub", "tron")["entity"] == "HTX"
    assert _one(db, "0x5041ed759dd4afc3a72b8192c143f72f4724081a", "ethereum")["entity"] == "OKX"


def test_an_exchange_published_label_beats_the_tagpack_row(tmp_path):
    db, stats = _db(tmp_path, wa="wa_overlap")
    row = _one(db, "0x0511509a39377f1c6c78db4330fbfcc16d8a602f", "ethereum")
    assert (row["tier"], row["source"]) == ("published_por", "defillama-cex")
    assert stats["duplicates_dropped"] == 1


def test_no_tagpack_csv_changes_nothing(fixture_db, tmp_path):
    _, before = fixture_db
    after = build_labels(tmp_path / "l.duckdb", FIX / "wa", FIX / "dune.csv",
                         tagpacks_csv=tmp_path / "missing.csv")
    assert after["total"] == before["total"] and after["tagpack_rows"] == 0


# ------------------------------------------------------------------ CLI
def test_cli_tagpacks_writes_the_csv_and_says_what_it_kept(tmp_path, capsys):
    from vaspfusion.cli import main
    out = tmp_path / "research" / "graphsense_tagpacks_exchange.csv"
    main(["tagpacks", "--packs", str(PACKS), "--out", str(out)])
    said = capsys.readouterr().out
    assert "16 exchange tags" in said and "BTC 13" in said and "ETH 2" in said and "TRX 1" in said
    with out.open(newline="") as fh:
        assert len(list(csv.DictReader(fh))) == 16


def test_cli_labels_picks_the_csv_up_from_the_research_folder(tmp_path, capsys):
    import shutil

    from vaspfusion.cli import main
    research = tmp_path / "research"
    shutil.copytree(FIX / "wa", research / "wallet-attribution" / "data")
    shutil.copy(FIX / "dune.csv", research / "indian_vasps_dune_spellbook.csv")
    main(["tagpacks", "--packs", str(PACKS), "--out",
          str(research / "graphsense_tagpacks_exchange.csv")])
    main(["labels", "--research", str(research), "--db", str(tmp_path / "l.duckdb"),
          "--derived", str(tmp_path / "none"), "--model", str(tmp_path / "none")])
    said = capsys.readouterr().out
    assert "GraphSense TagPacks (exchange packs): 16 rows, 16 kept" in said
    assert _one(tmp_path / "l.duckdb", "3BMEXbSSrK2K7cRgqxrtqUWfxowBBrW1BE", "bitcoin")
