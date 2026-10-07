"""Threat tags. Every fixture under tests/fixtures/threats is a real excerpt: whole SDN
entries of the official XML, records of the Ransomwhere export, and pack headers with
their first tags from the GraphSense TagPacks, all copied verbatim."""
from pathlib import Path

import duckdb
import pytest

from vaspfusion.labels import threats as T
from vaspfusion.labels.load import LABEL_COLUMNS, build_labels
from vaspfusion.labels.lookup import Label, LabelStore

FIX = Path(__file__).parent.parent / "fixtures"
RAW = FIX / "threats"


@pytest.fixture(scope="module")
def ofac():
    return {r["address"]: r for r in T.read_ofac(RAW / "sdn_excerpt.xml")}


@pytest.fixture(scope="module")
def tagged(tmp_path_factory):
    """A label DB built from the label fixtures with the threat fixtures joined on."""
    tmp = tmp_path_factory.mktemp("threats")
    rows = T.merge(T.read_ofac(RAW / "sdn_excerpt.xml")
                   + T.read_ransomwhere(RAW / "ransomwhere_excerpt.json")
                   + T.read_tagpacks(RAW / "packs"))
    T.write_csv(rows, tmp / "threat_tags.csv")
    db = tmp / "labels.duckdb"
    stats = build_labels(db, FIX / "labels" / "wa", FIX / "labels" / "dune.csv",
                         threats_csv=tmp / "threat_tags.csv")
    return db, stats, rows


# ------------------------------------------------------------------ OFAC
def test_a_counter_terrorism_programme_is_terrorism_financing(ofac):
    row = ofac["TBXMiRqUp1XH1zLazWu8cWitMAScv4HsYq"]
    assert (row["chain"], row["threat"]) == ("tron", "terrorism_financing")
    assert row["entity"] == "Miloud ABDERRAHMANE"
    assert "uid 57961" in row["evidence"] and "programme SDGT" in row["evidence"]
    assert "ISLAMIC STATE OF IRAQ AND THE LEVANT" in row["evidence"]     # the list's remark
    assert row["source_url"].endswith("Details.aspx?id=57961")


def test_a_cyber_entry_is_tagged_only_from_its_cited_designation(ofac):
    row = ofac["bc1qvhnfknw852ephxyc5hm4q520zmvf9maphetc9z"]
    assert (row["chain"], row["threat"]) == ("bitcoin", "ransomware")
    assert "programme CYBER2" in row["evidence"] and "LockBit" in row["evidence"]
    assert row["source_url"].endswith("/jy2326")


def test_a_programme_no_rule_names_is_sanctioned_other(ofac):
    row = ofac["0x098B716B8Aaf21512996dC57EB0615e2383E2f96"]
    assert (row["chain"], row["threat"], row["entity"]) == \
        ("ethereum", "sanctioned_other", "LAZARUS GROUP")
    assert "programme DPRK3" in row["evidence"]


def test_a_token_listing_is_filed_on_the_chain_its_address_is_valid_on(ofac):
    row = ofac["TA3941uFAvmVibSkQ6fMJXxmaSNovX86mz"]           # listed as USDT
    assert (row["chain"], row["threat"]) == ("tron", "sanctioned_other")
    assert "Listed as: USDT" in row["evidence"] and "published 2026-10-02" in row["evidence"]


def test_only_digital_currency_ids_are_read(ofac):
    assert "khoroshev1@icloud.com" not in ofac and "Male" not in ofac


def test_every_entity_override_cites_a_publication():
    for uid, e in T.config()["ofac"]["entities"].items():
        assert e["threat"] in T.threats() and e["basis"] and e["url"].startswith("https://")


# ------------------------------------------------------------------ Ransomwhere
def test_ransomwhere_keeps_the_family_as_the_entity():
    rows = {r["entity"]: r for r in T.read_ransomwhere(RAW / "ransomwhere_excerpt.json")}
    assert set(rows) == {"Netwalker (Mailto)", "Conti", "Unlabeled", "Locky"}
    conti = rows["Conti"]
    assert (conti["chain"], conti["threat"], conti["source"]) == \
        ("bitcoin", "ransomware", "ransomwhere")
    assert "family Conti" in conti["evidence"]


# ------------------------------------------------------------------ GraphSense
def test_tagpacks_are_read_by_their_own_abuse_and_category_fields():
    rows = T.read_tagpacks(RAW / "packs")
    by = {(r["address"], r["source"]): r for r in rows}
    hydra = by[("1BCWMwpR4M1nYUuuYe2bmzrNuwGoF9ZAbA", "graphsense-tagpack:hydra")]
    assert hydra["threat"] == "darknet_market" and hydra["entity"] == "Hydra Market"
    alpha = by[("13xq4uaSh9RSXofnBudVBSfx1Fmo6YqS1W", "graphsense-tagpack:walletexplorer")]
    assert alpha["threat"] == "darknet_market" and alpha["entity"] == "AlphaBayMarket"
    forfeit = by[("1421chCK32pV32Tw5MQbiUiKWKvnmj7d91",
                  "graphsense-tagpack:aft-alqaeda-forfeit_vc")]
    assert forfeit["threat"] == "terrorism_financing" and "abuse: terrorism" in forfeit["evidence"]
    phish = by[("0xD0cC2B24980CBCCA47EF755Da88B220a82291407",
                "graphsense-tagpack:etherscamdb_tagpack")]
    assert phish["threat"] == "fraud" and phish["chain"] == "ethereum"


def test_packs_that_say_something_else_are_not_read():
    sources = {r["source"] for r in T.read_tagpacks(RAW / "packs")}
    # NFT marketplaces, sextortion spam, exchange hacks, and the exchange tag of a pack
    # whose market tags are read
    assert "graphsense-tagpack:etherscan-wordcloud-market" not in sources
    assert "graphsense-tagpack:sextortion_talos" not in sources
    assert "graphsense-tagpack:hacks" not in sources
    assert all(r["entity"] != "Huobi.com" for r in T.read_tagpacks(RAW / "packs"))


# ------------------------------------------------------------------ merge
def test_the_more_specific_threat_wins_then_the_first_source():
    a = {"address": "1BCWMwpR4M1nYUuuYe2bmzrNuwGoF9ZAbA", "chain": "bitcoin",
         "entity": "x", "source_url": "", "evidence": ""}
    rows = T.merge([{**a, "threat": "sanctioned_other", "source": "ofac-sdn-xml"},
                    {**a, "threat": "darknet_market", "source": "graphsense-tagpack:hydra"}])
    assert [(r["threat"], r["source"]) for r in rows] == \
        [("darknet_market", "graphsense-tagpack:hydra")]
    rows = T.merge([{**a, "threat": "ransomware", "source": "graphsense-tagpack:ransomware"},
                    {**a, "threat": "ransomware", "source": "ransomwhere"}])
    assert rows[0]["source"] == "ransomwhere"


def test_merge_spells_addresses_as_the_store_does_and_drops_unusable_ones():
    base = {"threat": "fraud", "entity": "x", "source": "ransomwhere", "source_url": "",
            "evidence": ""}
    rows = T.merge([{**base, "address": "0xD0cC2B24980CBCCA47EF755Da88B220a82291407",
                     "chain": "ethereum"},
                    {**base, "address": "not-an-address", "chain": "bitcoin"}])
    assert [r["address"] for r in rows] == ["0xd0cc2b24980cbcca47ef755da88b220a82291407"]


def test_the_csv_round_trips(tmp_path):
    rows = T.merge(T.read_tagpacks(RAW / "packs"))
    T.write_csv(rows, tmp_path / "t.csv")
    assert T.read_csv(tmp_path / "t.csv") == rows
    assert T.read_csv(tmp_path / "missing.csv") == []


# ------------------------------------------------------------------ the label table
def _one(db, address, chain):
    with duckdb.connect(str(db), read_only=True) as con:
        row = con.execute(f"SELECT {', '.join(LABEL_COLUMNS)} FROM labels "
                          "WHERE address = ? AND chain = ?", [address, chain]).fetchone()
    return dict(zip(LABEL_COLUMNS, row)) if row else None


def test_a_tag_is_joined_onto_the_label_already_held(tagged):
    db, stats, _ = tagged
    row = _one(db, "TA3941uFAvmVibSkQ6fMJXxmaSNovX86mz", "tron")
    # the label is still the row of the list it was loaded from
    assert (row["category"], row["source"], row["entity"]) == ("sanctioned", "ofac-sdn", "OFAC SDN")
    assert row["threat"] == "sanctioned_other" and row["threat_entity"] == "CHEIL CREDIT BANK"
    assert row["threat_source"] == "ofac-sdn-xml" and "programme DPRK4" in row["threat_evidence"]
    assert stats["threat_joined"] >= 1


def test_a_tagged_address_nothing_else_labels_gets_a_label(tagged):
    db, stats, rows = tagged
    row = _one(db, "1BCWMwpR4M1nYUuuYe2bmzrNuwGoF9ZAbA", "bitcoin")
    assert (row["category"], row["entity"], row["tier"], row["kind"]) == \
        ("entity", "Hydra Market", "explorer_tag", "unknown")
    assert row["threat"] == "darknet_market"
    listed = _one(db, "TBXMiRqUp1XH1zLazWu8cWitMAScv4HsYq", "tron")
    assert (listed["category"], listed["tier"], listed["threat"]) == \
        ("sanctioned", "curated", "terrorism_financing")
    phish = _one(db, "0xd0cc2b24980cbcca47ef755da88b220a82291407", "ethereum")
    assert (phish["category"], phish["threat"]) == ("scam", "fraud")
    assert stats["threat_rows"] == len(rows)
    assert stats["threat_new_rows"] + stats["threat_joined"] == len(rows)


def test_counts_are_reported_per_threat_chain_and_source(tagged):
    _, stats, rows = tagged
    assert sum(stats["by_threat"].values()) == len(rows) + stats["scam_retagged"]
    assert stats["threat_by_chain"]["terrorism_financing"]["tron"] == 2
    assert stats["threat_by_source"]["darknet_market"] == {"graphsense-tagpacks": 5}


def test_without_a_threat_file_no_label_is_tagged(fixture_db):
    db, stats = fixture_db
    assert stats["threat_rows"] == 0 and stats["threat_new_rows"] == 0
    with duckdb.connect(str(db), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM labels WHERE threat IS NOT NULL "
                           "AND category <> 'scam'").fetchone()[0] == 0


def test_lookup_search_and_as_dict(tagged):
    db, _, _ = tagged
    with LabelStore(db) as store:
        lab = store.lookup("TBXMiRqUp1XH1zLazWu8cWitMAScv4HsYq", "tron")
        assert lab.threat == "terrorism_financing"
        d = lab.as_dict()
        assert d["threat_entity"] == "Miloud ABDERRAHMANE"
        assert Label.from_dict(d) == lab
        total, items = store.search(threat="darknet_market")
        assert total == 5 and {i.threat for i in items} == {"darknet_market"}
        assert store.search(threat="any")[0] == sum(store.stats()["by_threat"].values())
        plain = store.lookup("TAWK8YMnn7yAfnQRyvjiBv9ksocFt9qNdR", "tron")
        assert plain.threat is None and "threat" not in plain.as_dict()


def test_a_db_built_before_threat_tags_still_reads(tagged, tmp_path):
    db, _, _ = tagged
    old = tmp_path / "old.duckdb"
    with duckdb.connect(str(old)) as con:
        con.execute(f"ATTACH '{db}' AS src (READ_ONLY)")
        con.execute("CREATE TABLE labels AS SELECT * EXCLUDE (threat, threat_entity, "
                    "threat_source, threat_url, threat_evidence) FROM src.labels")
    with LabelStore(old) as store:
        assert store.lookup("TBXMiRqUp1XH1zLazWu8cWitMAScv4HsYq", "tron").threat is None
        assert store.search(threat="fraud") == (0, [])
        assert store.stats()["by_threat"] == {}


# ------------------------------------------------------------------ explorer name tags (E2)
def _rows(*rows):
    import polars as pl
    from vaspfusion.labels.load import LABEL_COLUMNS as COLS
    blank = {c: None for c in COLS}
    full = [{**blank, "chain": "ethereum", "category": "entity", "kind": "unknown",
             "tier": "explorer_tag", "source": "eth-labels", "source_url": "https://x",
             **r, "_promoted": False} for r in rows]
    schema = {c: pl.String for c in COLS} | {"confidence": pl.Float64, "confidence_low": pl.Float64,
                                              "confidence_high": pl.Float64, "_promoted": pl.Boolean}
    return pl.DataFrame(full, schema=schema)


def test_an_explorers_exploiter_or_phishing_tag_becomes_a_threat_tag_in_its_own_words():
    from vaspfusion.labels.load import _apply_threats
    df, stats = _apply_threats(_rows(
        {"address": "0x01", "entity": "Wazirx Exploit", "label": "WazirX Exploiter 4"},
        {"address": "0x02", "entity": "Kucoin Hacker", "label": "Kucoin Hacker"},
        {"address": "0x03", "entity": "Brand Infringement", "label": "Fake_Phishing1065264"},
        # not the wallet of a hack: a charity whose name contains the word, a whitehat
        {"address": "0x04", "entity": "Charity", "label": "Endaoment: Tampa Hackerspace"},
        {"address": "0x05", "entity": "Balancer", "label": "Balancer Exploit Whitehat 1"},
        # the same words from a source that is not the explorer's tags
        {"address": "0x06", "entity": "X", "label": "X Exploiter", "source": "dune-spellbook"},
        # an address a listed source already tagged keeps that tag
        {"address": "0x07", "entity": "Lazarus", "label": "Ronin Bridge Exploiter"},
    ), [{"address": "0x07", "chain": "ethereum", "threat": "sanctioned_other", "entity": "LAZARUS",
         "source": "ofac-sdn-xml", "source_url": "u", "evidence": "programme DPRK3"}])
    got = {r["address"]: r for r in df.to_dicts()}
    assert (got["0x01"]["threat"], got["0x01"]["threat_entity"], got["0x01"]["threat_source"]) == \
        ("theft", "Wazirx Exploit", "eth-labels")
    assert got["0x01"]["threat_evidence"] == ("Tagged as the wallet of a hack or exploit by "
                                              "the block explorer: WazirX Exploiter 4")
    assert got["0x02"]["threat"] == "theft" and got["0x03"]["threat"] == "fraud"
    assert "phishing address" in got["0x03"]["threat_evidence"]
    assert [got[a]["threat"] for a in ("0x04", "0x05", "0x06")] == [None, None, None]
    assert got["0x07"]["threat"] == "sanctioned_other"
    assert stats["explorer_tagged"] == 3
    # no category is changed: the outcome rules read the category, not the tag
    assert {r["category"] for r in got.values()} == {"entity"}
