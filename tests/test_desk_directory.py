"""The VASP directory holds only facts with a source: no field without a citation."""
from datetime import date

import pytest

from vaspfusion.api import schemas as S
from vaspfusion.desk.directory import DEFAULT_PATH, FACT_FIELDS, Directory, DirectoryError


@pytest.fixture(scope="module")
def directory():
    return Directory.load(DEFAULT_PATH)


def test_every_fact_in_the_tracked_file_names_a_source_that_exists(directory):
    assert len(directory.names()) >= 10
    for name in directory.names():
        raw = directory.raw(name)
        for field in FACT_FIELDS:
            if raw.get(field) is not None:
                assert raw["cites"].get(field), f"{name}.{field} has no source"
        for field, ids in raw["cites"].items():
            assert raw.get(field) is not None, f"{name} cites a source for an empty {field}"
            for sid in ids:
                assert sid in directory.sources, f"{name}.{field} cites unknown source {sid}"
    for sid, src in directory.sources.items():
        assert src["title"] and src["url"].startswith("https://") and src["accessed"], sid


def test_an_entry_is_shaped_like_the_contract(directory):
    for name in directory.names():
        S.VaspDirectoryEntry.model_validate(directory.get(name))


def test_coindcx_is_registered_per_the_lok_sabha_annexure(directory):
    e = directory.get("CoinDCX")
    assert e["legal_name"] == "Neblio Technologies Private Limited"
    assert e["fiu_ind_registered"] is True and e["fiu_ind_as_of"] == date(2023, 12, 4)
    assert e["jurisdiction"] == "India"
    cited = {s["field"]: s["url"] for s in e["sources"]}
    assert "sansad.in" in cited["fiu_ind_registered"] and "sansad.in" in cited["legal_name"]
    assert e["source_urls"] == sorted({s["url"] for s in e["sources"]})


def test_what_we_could_not_cite_is_blank(directory):
    okx = directory.get("OKX")
    assert okx["fiu_ind_registered"] is None and okx["legal_name"] is None
    assert okx["le_request_channel"].startswith("https://app.kodexglobal.com/okx")
    assert directory.get("CoinDCX")["le_request_channel"] is None


def test_an_exchange_we_hold_nothing_on_is_just_its_name(directory):
    assert directory.get("Some Exchange") == {
        "name": "Some Exchange", "legal_name": None, "fiu_ind_registered": None,
        "fiu_ind_as_of": None, "jurisdiction": None, "le_request_channel": None,
        "notes": [], "sources": [], "source_urls": []}


def test_aliases_and_case_resolve_to_the_label_stores_name(directory):
    assert directory.get("Huobi")["name"] == "HTX"
    assert directory.get("gate.io")["name"] == "Gate.io"


def test_a_fact_without_a_source_is_refused(tmp_path):
    bad = tmp_path / "d.yaml"
    bad.write_text("sources: {}\nvasps:\n  - name: X\n    legal_name: X Ltd\n")
    with pytest.raises(DirectoryError, match="legal_name"):
        Directory.load(bad)


def test_a_registration_fact_needs_its_date(tmp_path):
    bad = tmp_path / "d.yaml"
    bad.write_text("sources:\n  s: {title: T, url: 'https://x.example/a', accessed: 2026-10-02}\n"
                   "vasps:\n  - name: X\n    fiu_ind_registered: true\n"
                   "    cites: {fiu_ind_registered: [s]}\n")
    with pytest.raises(DirectoryError, match="fiu_ind_as_of"):
        Directory.load(bad)
