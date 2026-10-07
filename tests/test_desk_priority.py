"""Who to write to first: a stated rule over what the tool holds, and no response time."""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deskkit import demo_case  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402
from vaspfusion.desk.directory import Directory  # noqa: E402
from vaspfusion.desk.priority import (DIRECT, DOMESTIC, OFFSHORE, route_of,  # noqa: E402
                                      write_order)

DIRECTORY = Directory.load()


def _entry(**kw):
    return {"name": "X", "legal_name": None, "fiu_ind_registered": None, "fiu_ind_as_of": None,
            "jurisdiction": None, "le_request_channel": None, "notes": [], "sources": [], **kw}


class Stub:
    """A directory with chosen facts, to test the rule apart from the real file."""
    def __init__(self, **entries):
        self.entries = entries

    def canonical(self, name):
        return name

    def get(self, name):
        return _entry(name=name, **self.entries.get(name, {}))


def test_the_two_exchange_case_puts_the_registered_exchange_first():
    order = write_order(demo_case("tron-htx-coindcx"), DIRECTORY)
    S.WriteOrder.model_validate(order)
    first, second = order["exchanges"]
    assert (first["rank"], first["vasp"], first["route"]) == (1, "CoinDCX", DOMESTIC)
    assert (second["rank"], second["vasp"], second["route"]) == (2, "HTX", DIRECT)
    assert first["letter_of_request"] is False and second["letter_of_request"] is True
    assert "Registered with FIU-IND as of 4 Dec 2023 (an official list)." in first["reasons"]
    assert any("not on record" in r for r in second["reasons"])
    assert any(r.startswith("A law-enforcement channel is on record") for r in second["reasons"])
    assert first["reasons"][-1] == "No law-enforcement channel is on record for it."
    # the shares are the case's own
    case = demo_case("tron-htx-coindcx")
    shares = {c["vasp"]: c["share_of_funds"] for c in case["candidates"]
              if c["direction"] == "outbound" and c.get("request_wallets")}
    assert first["share_of_funds"] == pytest.approx(shares["CoinDCX"], abs=1e-4)
    assert second["share_of_funds"] == pytest.approx(shares["HTX"], abs=1e-4)
    assert first["amount"] == 6000 and second["amount"] == 7000


def test_within_a_group_the_larger_share_then_the_later_arrival_comes_first():
    case = demo_case("tron-htx-coindcx")
    order = write_order(case, Stub())            # nothing cited: one group
    assert [x["vasp"] for x in order["exchanges"]] == ["HTX", "CoinDCX"]    # 7,000 > 6,000
    assert all(x["route"] == OFFSHORE for x in order["exchanges"])
    for c in case["candidates"]:
        c["share_of_funds"] = 0.5
    arrivals = {c["vasp"]: max(w["reached_at"] for w in c["request_wallets"])
                for c in case["candidates"] if c.get("request_wallets")}
    later = max(arrivals, key=lambda v: str(arrivals[v]))
    order = write_order(case, Stub())
    assert order["exchanges"][0]["vasp"] == later
    assert "the most recent arrival among these exchanges" in \
        " ".join(order["exchanges"][0]["reasons"])


def test_a_published_channel_comes_before_neither_and_a_cited_no_is_said():
    case = demo_case("tron-htx-coindcx")
    order = write_order(case, Stub(CoinDCX={"le_request_channel": "le@example.test"},
                                   HTX={"fiu_ind_registered": False,
                                        "fiu_ind_as_of": date(2025, 10, 1)}))
    assert [(x["vasp"], x["route"]) for x in order["exchanges"]] == [
        ("CoinDCX", DIRECT), ("HTX", OFFSHORE)]
    assert "FIU-IND named it as operating without registration (as of 1 Oct 2025)." in \
        order["exchanges"][1]["reasons"]


def test_routes():
    assert route_of(_entry(fiu_ind_registered=True)) == DOMESTIC
    assert route_of(_entry(fiu_ind_registered=False, le_request_channel="x")) == DIRECT
    assert route_of(_entry()) == OFFSHORE


def test_one_exchange_still_says_where_to_write_and_none_gives_nothing():
    order = write_order(demo_case("tron-coindcx"), DIRECTORY)
    assert [x["vasp"] for x in order["exchanges"]] == ["CoinDCX"]
    assert "most recent" not in " ".join(order["exchanges"][0]["reasons"])
    assert write_order(demo_case("tron-abstain"), DIRECTORY) is None
    assert write_order({**demo_case("tron-coindcx"), "status": "running"}, DIRECTORY) is None


def test_an_open_request_is_shown_and_a_withdrawn_one_is_not():
    case = demo_case("tron-coindcx")
    req = {"id": "req-2026-0001", "vasp": "CoinDCX", "case_ids": ["tron-coindcx"],
           "status": "sent", "created_at": "2026-10-02T09:30:00Z"}
    row = write_order(case, DIRECTORY, [req])["exchanges"][0]
    assert (row["request_id"], row["request_status"]) == ("req-2026-0001", "sent")
    row = write_order(case, DIRECTORY, [{**req, "status": "withdrawn"}])["exchanges"][0]
    assert row["request_id"] is None


@pytest.mark.parametrize("case_id", ["tron-coindcx", "tron-htx-coindcx", "eth-bitget"])
def test_no_sentence_promises_a_response_time(case_id):
    order = write_order(demo_case(case_id), DIRECTORY)
    text = " ".join([order["rule"]] + [r for x in order["exchanges"] for r in x["reasons"]])
    for word in ("hour", "within a", "within 2", "respond", "fast", "typically", "usually"):
        assert word not in text.lower()
    assert "No response time is stated" in order["note"]
