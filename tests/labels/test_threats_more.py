"""Other governments' crypto lists (E7): the UK Sanctions List, the EU Financial Sanctions
File and Israel's NBCTF orders. The excerpts below are copied from the official files
(fetched 14 Oct 2026; research/data/threats/SOURCES.json), trimmed to the fields read."""
import json
from pathlib import Path

from vaspfusion.api.schemas import LabelOut
from vaspfusion.labels import threats as T
from vaspfusion.labels.lookup import Label


UK = """<?xml version="1.0" encoding="utf-8"?>
<Designations><DateGenerated>12/10/2026</DateGenerated>
 <Designation><UniqueID>RUS0000</UniqueID><RegimeName>The Russia (Sanctions) (EU Exit) Regulations 2019</RegimeName>
  <Names><Name><Name6>EXMO EXCHANGE LIMITED</Name6><NameType>Primary Name</NameType></Name></Names>
  <OtherInformation>EXMO EXCHANGE LIMITED is associated with the following crypto wallet addresses:  TJqUC56SDZ373JYRurzXtMcor2HQvN9BaU TVa1p4aTVoHuF4EDGthn57FbKNbu4DRJkQ  TCQqA58EmX6AnUZKPCogL2Q441B4ThbJGN </OtherInformation></Designation>
 <Designation><UniqueID>AFG0001</UniqueID><RegimeName>The Afghanistan (Sanctions) (EU Exit) Regulations 2020</RegimeName>
  <Names><Name><Name6>NO ADDRESS HERE</Name6><NameType>Primary Name</NameType></Name></Names>
  <OtherInformation>Phone 962788680555.</OtherInformation></Designation>
</Designations>"""

EU = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<export xmlns="http://eu.europa.ec/fpi/fsd/export" generationDate="2026-10-12T12:27:34.779+02:00">
 <sanctionEntity euReferenceNumber="EU.12747.39" logicalId="172907">
  <regulation programme="UKR" logicalId="208642"><publicationUrl>https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=OJ:L_202500389</publicationUrl></regulation>
  <nameAlias wholeName="Garantex" logicalId="172909"><remark>Place of registration: Moscow, Russian Federation Known Garantex blockchain wallet addresses: ETH: 0x002471b8A185f9980708d0eAEC5B289714F56f8d TRX: TA1hsikRfsgGiW9nEBpT4tEXEySTNYLr2d</remark></nameAlias>
 </sanctionEntity>
</export>"""

# NBCTF order 34/24 as its export gives it (the personal-name columns left empty here)
NBCTF = ("Name he,Name ar,Name en,Order Type,Order Number,Order Date,Validity Date,Is Correction Version,"
         "Correction Version Name,Is Canceled,Designated Operatives,Designated Organizations,"
         "Non-Designated Operatives,Non-Designated Organizations,Is Hidden,Descriptions,Order Documents,"
         "Previous Seizure Orders,Assets,Articles\n"
         'FO 34/24,FO 34/24,FO 34/24,FO (Forfeiture),34/24,2024-12-24,2028-02-16,False,,False,,,,,False,,,,'
         '"Name: TGN9S92YLBCiCCH5XuKpdDTHwACZL3e1jr\n\n-------------\nName: 962788680555\n",\n'
         'FO 15/22,FO 15/22,FO 15/22,FO (Forfeiture),15/22,2022-03-07,2024-12-29,False,,False,,,,,False,,,,'
         '"Name: TZ1bLdAGQPH9cQkR372TGZJ99fjBi1juTQ",\n'
         'X,X,X,ASO (Seizure),99/99,2026-01-01,2028-01-01,False,,True,,,,,False,,,,'
         '"Name: TB5UPBTtXYwwmSviWBkQcFM64o6R1CDXUY",\n')


def test_uk_reads_the_addresses_an_entry_names_and_its_regime(tmp_path):
    (tmp_path / "uk.xml").write_text(UK, encoding="utf-8")
    rows = T.read_uk(tmp_path / "uk.xml")
    assert [r["address"] for r in rows] == ["TJqUC56SDZ373JYRurzXtMcor2HQvN9BaU",
                                           "TVa1p4aTVoHuF4EDGthn57FbKNbu4DRJkQ",
                                           "TCQqA58EmX6AnUZKPCogL2Q441B4ThbJGN"]
    assert {r["threat"] for r in rows} == {"sanctioned_other"}
    assert rows[0]["entity"] == "EXMO EXCHANGE LIMITED" and rows[0]["source"] == T.UK_SOURCE
    assert "RUS0000" in rows[0]["evidence"] and "Russia (Sanctions)" in rows[0]["evidence"]


def test_eu_reads_the_remark_and_the_regulation(tmp_path):
    (tmp_path / "eu.xml").write_text(EU, encoding="utf-8")
    rows = T.read_eu(tmp_path / "eu.xml")
    assert [(r["address"], r["chain"]) for r in rows] == [
        ("0x002471b8A185f9980708d0eAEC5B289714F56f8d", "ethereum"),
        ("TA1hsikRfsgGiW9nEBpT4tEXEySTNYLr2d", "tron")]
    assert rows[0]["source_url"].startswith("https://eur-lex.europa.eu/")
    assert "EU.12747.39: Garantex; programme UKR" in rows[0]["evidence"]


def test_nbctf_keeps_crypto_addresses_only_skips_a_cancelled_order_and_says_when_one_lapsed(tmp_path):
    (tmp_path / "n.csv").write_text("﻿" + NBCTF, encoding="utf-8")
    rows = T.read_nbctf(tmp_path / "n.csv", today="2026-10-14")
    assert [r["address"] for r in rows] == ["TGN9S92YLBCiCCH5XuKpdDTHwACZL3e1jr",
                                           "TZ1bLdAGQPH9cQkR372TGZJ99fjBi1juTQ"]
    assert {r["threat"] for r in rows} == {"terrorism_financing"}
    assert rows[0]["entity"] == "NBCTF order 34/24"
    assert "valid until 2028-02-16." in rows[0]["evidence"]
    assert "valid until 2024-12-29 (that date has passed)" in rows[1]["evidence"]


def test_an_address_two_lists_name_keeps_both():
    a = "TA1hsikRfsgGiW9nEBpT4tEXEySTNYLr2d"
    rows = [{"address": a, "chain": "tron", "threat": "sanctioned_other", "entity": "Garantex",
             "source": T.EU_SOURCE, "source_url": "eu", "evidence": "EU entry"},
            {"address": a, "chain": "tron", "threat": "sanctioned_other",
             "entity": "GARANTEX EUROPE OU", "source": T.OFAC_SOURCE, "source_url": "ofac",
             "evidence": "OFAC entry"}]
    [row] = T.merge(rows)
    assert row["source"] == T.OFAC_SOURCE                      # the earlier source leads
    assert json.loads(row["also"]) == [{"source": T.EU_SOURCE, "entity": "Garantex",
                                        "threat": "sanctioned_other", "url": "eu",
                                        "evidence": "EU entry"}]
    [alone] = T.merge(rows[:1])
    assert alone["also"] == ""


def test_a_label_reads_every_listing_and_one_listing_reads_as_before():
    base = dict(address="a", chain="tron", entity="X", category="sanctioned", kind="unknown",
                tier="curated", source=T.OFAC_SOURCE, source_url=None, label="X",
                threat="sanctioned_other", threat_entity="X", threat_source=T.OFAC_SOURCE)
    one = Label(**base)
    assert "threat_also" not in one.as_dict()
    assert "threat_also" not in LabelOut.model_validate(one.as_dict()).model_dump()
    also = [{"source": T.EU_SOURCE, "entity": "Garantex", "threat": "sanctioned_other",
             "url": None, "evidence": "EU entry"}]
    two = Label(**base, threat_also=json.dumps(also, sort_keys=True))
    assert two.as_dict()["threat_also"] == also
    assert Label.from_dict(two.as_dict()) == two


def test_the_record_of_the_official_files_names_each_with_its_licence():
    rec = json.loads((Path(__file__).resolve().parents[2] / "data" / "threat_sources.json").read_text())
    by = rec["counts"]["by_source"]
    assert by["terrorism_financing"]["il-nbctf"] > 700
    assert by["sanctioned_other"]["uk-sanctions-list"] >= 1 and by["sanctioned_other"]["eu-fsf"] >= 1
    for name in ("uk_sanctions_list.xml", "eu_fsf_full.xml", "nbctf_crypto_orders.csv"):
        assert name in rec["files"] and rec["files"][name]["licence"]
