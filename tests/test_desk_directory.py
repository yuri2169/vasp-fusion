"""The VASP directory holds only facts with a source: no field without a citation."""
from datetime import date

import pytest

from vaspfusion.api import schemas as S
from vaspfusion.desk.directory import DEFAULT_PATH, Directory, DirectoryError


@pytest.fixture(scope="module")
def directory():
    return Directory.load(DEFAULT_PATH)


def test_the_tracked_file_loads_and_every_source_in_it_is_used(directory):
    assert len(directory.names()) >= 10
    used = {sid for name in directory.names() for ids in directory.raw(name)["cites"].values()
            for sid in ids}
    used |= {sid for name in directory.names() for n in directory.raw(name).get("notes") or []
             for sid in n["cites"]}
    assert used == set(directory.sources)
    assert {s["kind"] for s in directory.sources.values()} == {"official", "exchange", "news"}


def test_an_entry_is_shaped_like_the_contract(directory):
    for name in directory.names():
        S.VaspDirectoryEntry.model_validate(directory.get(name))


def test_coindcx_is_registered_per_the_lok_sabha_annexure(directory):
    e = directory.get("CoinDCX")
    assert e["legal_name"] == "Neblio Technologies Private Limited"
    assert e["fiu_ind_registered"] is True and e["fiu_ind_as_of"] == date(2023, 12, 4)
    assert e["jurisdiction"] is None            # the annexure does not state it
    cited = {s["field"]: s for s in e["sources"]}
    assert set(cited) == {"legal_name", "fiu_ind_registered"}
    assert all("sansad.in" in s["url"] and s["kind"] == "official" for s in cited.values())
    assert e["source_urls"] == sorted({s["url"] for s in e["sources"]})


def test_a_self_reported_registration_says_so(directory):
    e = directory.get("Binance")
    assert e["fiu_ind_registered"] is True
    assert [s["kind"] for s in e["sources"] if s["field"] == "fiu_ind_registered"] == ["exchange"]
    assert any("own statement" in n for n in e["notes"])
    assert {s["field"] for s in e["sources"]} == {"fiu_ind_registered", "le_request_channel",
                                                  "notes"}


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


SRC = ("sources:\n  s: {title: T, url: 'https://x.example/a', accessed: 2026-10-02, "
       "published: 2026-01-05, kind: official}\n")


@pytest.mark.parametrize("entry, words", [
    ("  - name: X\n    legal_name: X Ltd\n", "legal_name has no source"),
    ("  - name: X\n    legal_name: X Ltd\n    cites: {legal_name: [nope]}\n", "unknown source"),
    ("  - name: X\n    cites: {legal_name: [s]}\n", "empty legal_name"),
    ("  - name: X\n    notes: ['registered']\n", "a note must be"),
    ("  - name: X\n    notes: [{text: registered}]\n", "a note has no source"),
    ("  - name: X\n    fiu_ind_registered: true\n    cites: {fiu_ind_registered: [s]}\n",
     "needs fiu_ind_as_of"),
    ("  - name: X\n    fiu_ind_registered: true\n    fiu_ind_as_of: 2026-10-01\n"
     "    cites: {fiu_ind_registered: [s]}\n", "is not the date its source was published"),
    ("  - name: X\n    fiu_ind_registered: 'yes'\n    fiu_ind_as_of: 2026-01-05\n"
     "    cites: {fiu_ind_registered: [s]}\n", "must be true or false"),
    ("  - name: X\n    fiu_ind_as_of: 2026-01-05\n", "without fiu_ind_registered"),
    ("  - name: X\n  - name: X\n", "listed twice"),
    ("  - legal_name: X Ltd\n", "has no name"),
    ("  - name: X\n  - name: Y\n    aliases: [x]\n", "names two exchanges"),
])
def test_a_file_that_breaks_the_rule_is_refused(tmp_path, entry, words):
    bad = tmp_path / "d.yaml"
    bad.write_text(SRC + "vasps:\n" + entry)
    with pytest.raises(DirectoryError, match=words):
        Directory.load(bad)


def test_a_source_needs_its_kind(tmp_path):
    bad = tmp_path / "d.yaml"
    bad.write_text("sources:\n  s: {title: T, url: 'https://x.example/a', "
                   "accessed: 2026-10-02}\nvasps: []\n")
    with pytest.raises(DirectoryError, match="has no kind"):
        Directory.load(bad)


def test_a_dated_cited_registration_loads(tmp_path):
    ok = tmp_path / "d.yaml"
    ok.write_text(SRC + "vasps:\n  - name: X\n    fiu_ind_registered: false\n"
                  "    fiu_ind_as_of: 2026-01-05\n    cites: {fiu_ind_registered: [s]}\n"
                  "    notes: [{text: 'Named in a notice.', cites: [s]}]\n")
    e = Directory.load(ok).get("x")
    assert (e["fiu_ind_registered"], e["notes"]) == (False, ["Named in a notice."])
    assert [s["field"] for s in e["sources"]] == ["fiu_ind_registered", "notes"]
