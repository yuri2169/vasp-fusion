"""The dashboard counts stored records. Run on five real demo cases (the interface's
own fixtures: `GET /api/cases/<id>` of the recorded demo wallets)."""
import json
from datetime import date
from pathlib import Path

import pytest

from vaspfusion.dashboard import build_dashboard, case_alerts
from vaspfusion.desk.routing import build_desk

FIXTURES = Path(__file__).resolve().parents[1] / "ui" / "src" / "test" / "fixtures" / "cases"
IDS = ("eth-bridge", "tron-abstain", "tron-coindcx", "tron-htx-coindcx", "tron-ofac")


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    return [json.loads((FIXTURES / f"{i}.json").read_text()) for i in IDS]


def _dash(cases, requests=()):
    desk = build_desk(cases, list(requests), date(2026, 10, 4))
    return build_dashboard(cases, desk, list(requests))


def test_outcomes_count_every_finished_case_once(cases):
    d = _dash(cases)
    assert d["outcomes"] == {"ATTRIBUTED": 2, "INSUFFICIENT_EVIDENCE": 2,
                             "SANCTIONED_OR_MIXER_REACHED": 1}
    assert d["counts"]["cases_total"] == 5
    assert d["counts"]["wallets_attributed"] == 2
    assert sum(d["outcomes"].values()) == 5


def test_chain_mix_adds_up_to_the_cases(cases):
    d = _dash(cases)
    assert d["chain_mix"] == [{"chain": "tron", "cases": 4}, {"chain": "ethereum", "cases": 1}]


def test_top_exchanges_are_the_desk_rows(cases):
    d = _dash(cases)
    by = {v["vasp"]: v for v in d["top_vasps"]}
    assert by["CoinDCX"] == {"vasp": "CoinDCX", "cases": 2, "total_usd": 7530.0}
    assert by["HTX"]["cases"] == 1 and by["HTX"]["total_usd"] == 7000.0
    assert [v["vasp"] for v in d["top_vasps"]] == ["CoinDCX", "HTX"]   # largest sum first


def test_a_case_is_open_until_the_exchange_has_replied(cases):
    d = _dash(cases)
    # both attributed cases route wallets nobody has asked about; the others have none
    assert d["counts"]["open_cases"] == 2
    assert d["counts"]["awaiting_request"] == 2          # CoinDCX and HTX
    assert d["counts"]["requests_awaiting_reply"] == 0


def test_requests_move_the_counts(cases):
    desk = build_desk(cases, [], date(2026, 10, 4))
    wallets = lambda vasp, case_ids: [  # noqa: E731 - the letter rows a request would carry
        {"case_id": c["id"], "address": w["address"], "amount_usd": w["amount"]}
        for c in cases if c["id"] in case_ids
        for cand in c["candidates"] if cand["vasp"] == vasp and cand.get("request_wallets")
        for w in cand["request_wallets"]]
    req = {"id": "req-1", "vasp": "CoinDCX", "status": "sent", "created_at": "2026-10-03T00:00:00Z",
           "due": "2026-10-10", "case_ids": ["tron-coindcx", "tron-htx-coindcx"],
           "letter": {"wallets": wallets("CoinDCX", ("tron-coindcx", "tron-htx-coindcx"))}}
    assert desk["rows"]
    d = _dash(cases, [req])
    assert d["counts"]["requests_awaiting_reply"] == 1
    assert d["counts"]["awaiting_request"] == 1          # HTX only
    assert d["counts"]["open_cases"] == 2                # sent is not replied
    d = _dash(cases, [{**req, "status": "answered"}])
    assert d["counts"]["requests_awaiting_reply"] == 0
    assert d["counts"]["open_cases"] == 1                # tron-htx-coindcx still owes HTX


def test_median_time_is_over_the_cases_that_name_an_exchange(cases):
    d = _dash(cases)
    named = [c for c in cases if c["top_vasp"]]
    times = sorted(next(k["time_to_reach_s"] for k in c["candidates"] if k["vasp"] == c["top_vasp"])
                   for c in named)
    assert d["attribution_times_n"] == len(times) >= 2
    assert min(times) <= d["median_time_to_attribution_s"] <= max(times)
    assert build_dashboard([], {"rows": []}, [])["median_time_to_attribution_s"] is None


def test_alerts_are_the_high_severity_flags_verbatim(cases):
    ofac = next(c for c in cases if c["id"] == "tron-ofac")
    flag = next(f for f in ofac["typology_flags"] if f["severity"] == "high")
    alerts = case_alerts(ofac)
    assert alerts and alerts[0]["text"].endswith(flag["text"])
    assert alerts[0]["wallet"] == flag["wallet"] and alerts[0]["case_id"] == "tron-ofac"
    d = _dash(cases)
    assert all(a["severity"] == "high" for a in d["recent_alerts"])
    assert [a["at"] for a in d["recent_alerts"]] == sorted((a["at"] for a in d["recent_alerts"]),
                                                            reverse=True)


def test_a_tracing_or_failed_case_is_counted_and_has_no_outcome(cases):
    running = {**cases[0], "id": "x", "status": "running", "outcome": None}
    failed = {**cases[1], "id": "y", "status": "failed", "outcome": None, "typology_flags": []}
    d = _dash([*cases, running, failed])
    assert d["counts"]["tracing"] == 1 and d["counts"]["failed"] == 1
    assert d["counts"]["cases_total"] == 7 and sum(d["outcomes"].values()) == 5
    assert d["counts"]["open_cases"] == 3


def test_watch_alerts_are_merged_newest_first(cases):
    desk = build_desk(cases, [], date(2026, 10, 4))
    alert = {"wallet": "TXYZ", "chain": "tron", "severity": "warn", "at": "2030-01-01T00:00:00Z",
             "case_id": "tron-coindcx", "text": "Watched wallet: 2 new transfers"}
    d = build_dashboard(cases, desk, [], [alert], watched=3)
    assert d["recent_alerts"][0] == alert and d["counts"]["watched"] == 3


def test_finished_cases_are_counted_by_risk_class(cases):
    from vaspfusion import risk
    dash = build_dashboard(cases, {"rows": []}, [])
    done = [c for c in cases if c.get("status") == "done"]
    assert sum(dash["risk_classes"].values()) == len(done)
    assert list(dash["risk_classes"]) == list(risk.CLASSES)
    ofac = next(c for c in cases if c["id"] == "tron-ofac")
    assert risk.case_risk(ofac)["risk_class"] == "severe" and dash["risk_classes"]["severe"] >= 1
