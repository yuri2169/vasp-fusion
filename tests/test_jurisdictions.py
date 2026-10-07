"""Traced money by the exchange's cited jurisdiction, on the real recorded cases and the
real directory. A country is never inferred: no cited jurisdiction, no place."""
import json
from datetime import date
from pathlib import Path

import pytest

from vaspfusion.api import schemas as S
from vaspfusion.desk.directory import Directory
from vaspfusion.desk.jurisdictions import BASIS, destinations
from vaspfusion.desk.routing import build_desk

FIXTURES = Path(__file__).resolve().parents[1] / "ui" / "src" / "test" / "fixtures" / "cases"
IDS = ("eth-bridge", "tron-abstain", "tron-coindcx", "tron-htx-coindcx", "tron-ofac")
SRC = ("sources:\n  s: {title: T, url: 'https://x.example/a', accessed: 2026-10-08, "
       "published: 2026-01-05, kind: official}\n")


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    return [json.loads((FIXTURES / f"{i}.json").read_text()) for i in IDS]


@pytest.fixture(scope="module")
def directory() -> Directory:
    return Directory.load()


def test_money_is_placed_where_each_exchange_is_cited_to_be(cases, directory):
    d = destinations(cases, directory)
    S.DestinationsByJurisdiction.model_validate(d)
    assert d["basis"] == BASIS == "Where the exchange is registered, not where the suspect is."
    by = {p["jurisdiction"]: p for p in d["places"]}
    assert set(by) == {"India", "Panama"} and d["not_on_record"] == []
    assert [p["jurisdiction"] for p in d["places"]] == ["India", "Panama"]   # largest first
    india, = by["India"]["exchanges"]
    assert (india["vasp"], india["total_usd"], india["wallets"]) == ("CoinDCX", 7530.0, 2)
    assert india["case_ids"] == ["tron-coindcx", "tron-htx-coindcx"]
    assert india["fiu_ind_registered"] is True and india["fiu_ind_as_of"] == date(2024, 12, 2)
    assert india["source_urls"] and "coindcx" in india["source_urls"][0]
    assert by["Panama"]["exchanges"][0]["vasp"] == "HTX" and by["Panama"]["total_usd"] == 7000.0


def test_the_sums_are_the_request_desks(cases, directory):
    desk = build_desk(cases, [], date(2026, 10, 8), canonical=directory.canonical)
    d = destinations(cases, directory)
    placed = {e["vasp"]: e["total_usd"] for p in d["places"] for e in p["exchanges"]}
    assert placed == {r["vasp"]: r["total_usd"] for r in desk["rows"]}


def test_one_case_shows_only_its_own_exchanges(cases, directory):
    one = next(c for c in cases if c["id"] == "tron-coindcx")
    d = destinations([one], directory)
    assert [(p["jurisdiction"], p["case_ids"]) for p in d["places"]] == [("India", ["tron-coindcx"])]
    abstain = next(c for c in cases if c["id"] == "tron-abstain")
    assert destinations([abstain], directory) == {"basis": BASIS, "places": [],
                                                  "not_on_record": []}


def test_an_exchange_without_a_cited_jurisdiction_is_listed_apart_never_placed(cases, tmp_path):
    path = tmp_path / "directory.yaml"
    path.write_text(SRC + "vasps:\n  - name: CoinDCX\n    jurisdiction: India\n"
                    "    cites: {jurisdiction: [s]}\n")
    d = destinations(cases, Directory.load(path))
    assert [p["jurisdiction"] for p in d["places"]] == ["India"]
    assert [(e["vasp"], e["total_usd"], e["source_urls"]) for e in d["not_on_record"]] == [
        ("HTX", 7000.0, [])]


def test_an_asset_with_no_dollar_price_is_counted_not_summed(cases, directory):
    one = json.loads(json.dumps(next(c for c in cases if c["id"] == "tron-coindcx")))
    one["asset"] = "TRX"
    for c in one["candidates"]:
        for w in c.get("request_wallets") or []:
            w["asset"] = "TRX"
    place, = destinations([one], directory)["places"]
    assert (place["total_usd"], place["wallets"], place["unpriced_wallets"]) == (0.0, 1, 1)
