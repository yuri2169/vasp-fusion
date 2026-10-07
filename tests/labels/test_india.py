"""Providers registered with FIU-IND against the label store. The store is the fixture
store (real rows); the list is the tracked file, or a cut-down copy of it."""
import json
from datetime import date

import pytest

from vaspfusion.api import schemas as S
from vaspfusion.labels.india import ListError, coverage, load_list, markdown, recorded_cases
from vaspfusion.labels.lookup import LabelStore

TRACEABLE = ("tron", "ethereum", "bitcoin")
SOURCE = ("source: {title: T, publisher: P, url: 'https://x.example/a', licence: L, "
          "published: 2024-12-02, accessed: 2026-10-08}\n")


def test_the_tracked_list_is_the_annexure_of_december_2024():
    listed = load_list()
    assert len(listed["providers"]) == 47
    assert listed["source"]["published"] == date(2024, 12, 2)
    assert "sansad.in" in listed["source"]["url"]
    first, last = listed["providers"][0], listed["providers"][-1]
    assert (first["legal_name"], first["trade_name"], first["names"]) == (
        "Neblio Technologies Private Limited", "Coin DCX", ["CoinDCX"])
    assert (last["n"], last["legal_name"], last["names"]) == (
        47, "Binance International Limited", ["Binance"])
    # the list gives five entities no trade name; they are never matched by name
    blank = [p for p in listed["providers"] if not p.get("trade_name")]
    assert len(blank) == 5 and all(p["names"] == [] for p in blank)
    # a trade name another company shares is never matched either
    assert next(p for p in listed["providers"] if p.get("trade_name") == "Square")["names"] == []


@pytest.mark.parametrize("text, words", [
    ("providers: []\n", "the source has no title"),
    (SOURCE + "providers:\n  - {n: 2, legal_name: X}\n", "out of the list's order"),
    (SOURCE + "providers:\n  - {n: 1}\n", "no legal_name"),
    (SOURCE + "providers:\n  - {n: 1, legal_name: X, names: X}\n", "must be a list"),
])
def test_a_broken_list_is_refused(tmp_path, text, words):
    path = tmp_path / "list.yaml"
    path.write_text(text)
    with pytest.raises(ListError, match=words):
        load_list(path)


@pytest.fixture
def small(tmp_path):
    listed = tmp_path / "list.yaml"
    listed.write_text(SOURCE + "providers:\n"
                      "  - {n: 1, legal_name: Neblio Technologies Private Limited, "
                      "trade_name: Coin DCX, names: [CoinDCX]}\n"
                      "  - {n: 2, legal_name: Zanmai Labs Pvt Ltd, trade_name: WazirX}\n"
                      "  - {n: 3, legal_name: Unocoin Technologies Pvt Ltd, trade_name: Unocoin}\n"
                      "  - {n: 4, legal_name: Ante Multimedia Pvt Ltd}\n")
    cases = tmp_path / "expected.json"
    cases.write_text(json.dumps({"tron-coindcx": {"top_vasp": "CoinDCX"},
                                 "tron-abstain": {"top_vasp": None},
                                 "bnb-coindcx": {"top_vasp": "CoinDCX"}}))
    return listed, cases


def test_a_provider_is_counted_by_chain_and_tier_and_by_the_cases_that_name_it(fixture_db, small):
    with LabelStore(fixture_db[0]) as store:
        cov = coverage(store, TRACEABLE, *small)
    S.IndianCoverage.model_validate(cov)
    assert (cov["listed"], cov["in_recorded_cases"]) == (4, 1)
    dcx = cov["providers"][0]
    assert dcx["can_name"] is True and dcx["labels"] == sum(dcx["by_chain"].values()) > 0
    assert dcx["traceable_labels"] == sum(n for c, n in dcx["by_chain"].items()
                                          if c in (*TRACEABLE, "evm"))
    assert dcx["recorded_cases"] == ["bnb-coindcx", "tron-coindcx"]
    assert sum(dcx["by_tier"].values()) == dcx["labels"]
    assert cov["source"]["published"] == "2024-12-02"


def test_a_provider_with_no_label_cannot_be_named_and_the_table_says_so(fixture_db, small):
    with LabelStore(fixture_db[0]) as store:
        cov = coverage(store, TRACEABLE, *small)
    unocoin, unnamed = cov["providers"][2], cov["providers"][3]
    for row in (unocoin, unnamed):
        assert (row["labels"], row["by_chain"], row["can_name"]) == (0, {}, False)
    assert cov["can_name"] == sum(r["can_name"] for r in cov["providers"])
    table = markdown(cov)
    assert "| 3 | Unocoin Technologies Pvt Ltd | Unocoin | 0 | none | none | none | **no** |" in table
    assert "| 4 | Ante Multimedia Pvt Ltd | (none listed) | 0 |" in table


def test_labels_on_chains_the_tool_cannot_trace_do_not_make_a_provider_nameable(fixture_db, small):
    with LabelStore(fixture_db[0]) as store:
        cov = coverage(store, (), *small)           # nothing traceable but `evm` rows
        dcx = cov["providers"][0]
        assert dcx["traceable_labels"] == dcx["by_chain"].get("evm", 0)
        assert dcx["labels"] > dcx["traceable_labels"]


def test_the_recorded_cases_are_read_from_the_tracked_demo_figures():
    cases = recorded_cases()
    assert "tron-coindcx" in cases["coindcx"] and "eth-bitget" in cases["bitget"]
    assert recorded_cases("/nonexistent/expected.json") == {}
