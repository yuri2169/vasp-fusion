"""The case timeline: only what the tool recorded, at the time it recorded it."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deskkit import NOW, demo_case  # noqa: E402
from vaspfusion.api import schemas as S  # noqa: E402
from vaspfusion.desk.timeline import case_timeline, elapsed_words  # noqa: E402


def _z(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


RECEIVED = NOW - timedelta(seconds=20)
COMPLAINT = {"complaint_ref": "NCRP/2026/000123", "received_at": _z(RECEIVED),
             "wallets": [{"case_id": "tron-coindcx"}]}
JOB = {"state": "done", "enqueued_at": (RECEIVED + timedelta(seconds=1)).timestamp(),
       "claimed_at": (RECEIVED + timedelta(seconds=2)).timestamp(),
       "finished_at": (RECEIVED + timedelta(seconds=14)).timestamp(),
       "worker": "host:1:0", "stats": {"seconds": 11.8}, "error": None}


def _request(*events, vasp="CoinDCX", rid="req-2026-0001"):
    return {"id": rid, "reference": "VF/REQ/2026/0001", "vasp": vasp,
            "case_ids": ["tron-coindcx"], "status": events[-1][0],
            "status_history": [{"status": s, "at": _z(NOW + timedelta(minutes=m)), "note": None,
                                **({"by": by} if by else {})} for s, m, by in events]}


def _timeline(**kw):
    args = {"complaints": [], "job": None, "opened": [], "requests": [],
            "letters_of_request": [], "named": ["CoinDCX"]}
    out = case_timeline(demo_case("tron-coindcx"), **{**args, **kw})
    S.CaseTimeline.model_validate(out)
    return out


def _step(timeline, key):
    return next(s for s in timeline["steps"] if s["key"] == key)


def test_the_exchange_is_named_so_long_after_the_complaint_by_two_recorded_times():
    t = _timeline(complaints=[COMPLAINT], job=JOB)
    received, named = _step(t, "complaint_received"), _step(t, "exchange_named")
    assert received["at"] == _z(RECEIVED) and received["source"] == "complaint store"
    assert received["detail"] == "NCRP/2026/000123" and received["after_previous_s"] is None
    assert named["at"] == _z(RECEIVED + timedelta(seconds=14))
    assert named["since_first_s"] == 14.0 and named["label"] == "Exchange named: CoinDCX"
    started, finished = _step(t, "trace_started"), _step(t, "trace_finished")
    assert started["after_previous_s"] == 2.0 and finished["after_previous_s"] == 12.0
    assert finished["source"] == "trace queue" and started["by"] is None


def test_a_case_stored_from_the_command_line_says_what_is_not_on_record():
    t = _timeline()
    opened, started, stored = (_step(t, k) for k in ("case_opened", "trace_started",
                                                     "trace_finished"))
    assert opened["state"] == started["state"] == "not_recorded"
    assert opened["at"] is None and started["at"] is None
    assert stored["state"] == "done" and stored["source"] == "case store"
    assert stored["at"] == _z(NOW) and stored["since_first_s"] == 0.0


def test_an_officer_opening_the_case_is_read_from_the_audit_log():
    row = {"at": "2026-10-02T09:29:50.250Z", "officer": "arao", "action": "case.open",
           "target": "tron-coindcx", "status": 202}
    t = _timeline(opened=[row], job=JOB)
    opened = _step(t, "case_opened")
    assert (opened["by"], opened["source"], opened["state"]) == ("arao", "audit log", "done")
    assert opened["at"] == "2026-10-02T09:29:50Z"


def test_a_step_that_has_not_happened_is_pending_and_never_has_a_time():
    t = _timeline(job=JOB, requests=[_request(("drafted", 1, "arao"), ("approved", 3, "arao"))])
    keys = [(s["key"], s["state"]) for s in t["steps"] if s["key"].startswith("request")]
    assert keys == [("request_drafted", "done"), ("request_approved", "done"),
                    ("request_sent", "pending"), ("request_acknowledged", "pending"),
                    ("request_replied", "pending")]
    for s in t["steps"]:
        if s["state"] != "done":
            assert s["at"] is None and s["after_previous_s"] is None \
                and s["since_first_s"] is None
    approved = _step(t, "request_approved")
    assert approved["by"] == "arao" and approved["after_previous_s"] == 120.0
    assert approved["request_id"] == "req-2026-0001"


def test_a_named_exchange_with_no_request_shows_the_draft_as_pending():
    t = _timeline(job=JOB, requests=[_request(("drafted", 1, None), ("withdrawn", 2, None))])
    assert [s["state"] for s in t["steps"] if s["key"] == "request_withdrawn"] == ["done"]
    last = t["steps"][-1]
    assert (last["key"], last["state"], last["label"]) == (
        "request_drafted", "pending", "Request to CoinDCX: not drafted")


def test_a_closed_request_leaves_nothing_pending():
    done = _request(("drafted", 1, None), ("approved", 2, None), ("sent", 3, None),
                    ("freeze_confirmed", 60, None))
    t = _timeline(job=JOB, requests=[done])
    assert not [s for s in t["steps"] if s["state"] == "pending"]
    assert _step(t, "request_freeze_confirmed")["label"] == \
        "Freeze confirmed by CoinDCX (VF/REQ/2026/0001)"


def test_a_running_trace_is_pending_past_its_start():
    job = {**JOB, "state": "running", "finished_at": None}
    case = {**demo_case("tron-coindcx"), "status": "running"}
    t = case_timeline(case, complaints=[], job=job, opened=[], requests=[],
                      letters_of_request=[], named=[])
    assert _step(t, "trace_started")["state"] == "done"
    assert _step(t, "trace_finished")["state"] == "pending"
    assert not [s for s in t["steps"] if s["key"] == "exchange_named"]


def test_a_letter_of_request_draft_is_a_step_from_its_audit_row():
    row = {"at": "2026-10-02T10:00:00.000Z", "officer": "arao", "target": "HTX",
           "detail": {"cases": ["tron-coindcx"]}}
    t = _timeline(job=JOB, letters_of_request=[row], named=[])
    step = _step(t, "letter_of_request_drafted")
    assert step["label"] == "Letter-of-request draft for HTX made" and step["by"] == "arao"
    assert "not sent" in step["detail"].lower()


def test_no_step_carries_a_time_that_is_not_in_a_record():
    inputs = {"complaints": [COMPLAINT], "job": JOB,
              "requests": [_request(("drafted", 1, None), ("approved", 2, None),
                                    ("sent", 3, None))]}
    on_record = set()
    for found in json.dumps(inputs).split('"'):
        if found[:2] == "20" and found.endswith("Z"):
            on_record.add(found)
    on_record |= {_z(datetime.fromtimestamp(JOB[k], timezone.utc))
                  for k in ("claimed_at", "finished_at")}
    t = _timeline(**inputs)
    assert {s["at"] for s in t["steps"] if s["at"]} <= on_record


def test_elapsed_words():
    assert elapsed_words(14) == "14 s" and elapsed_words(0.4) == "under 1 s"
    assert elapsed_words(150) == "2 min 30 s" and elapsed_words(3 * 3600 + 120) == "3 h 2 min"
    assert elapsed_words(2 * 86400 + 3600) == "2 d 1 h"


def test_the_result_is_stored_before_the_queue_row_closes_and_that_time_is_shown():
    stored = RECEIVED + timedelta(seconds=13, milliseconds=400)
    case = {**demo_case("tron-coindcx"), "created_at": stored}
    drafted = {"id": "req-2026-0001", "reference": "VF/REQ/2026/0001", "vasp": "CoinDCX",
               "case_ids": ["tron-coindcx"], "status": "drafted",
               "status_history": [{"status": "drafted", "note": None, "at": _z(
                   RECEIVED + timedelta(seconds=13))[:-1] + ".700Z"}]}
    t = case_timeline(case, complaints=[COMPLAINT], job=JOB, opened=[], requests=[drafted],
                      letters_of_request=[], named=["CoinDCX"])
    keys = [s["key"] for s in t["steps"] if s["state"] == "done"]
    assert keys.index("trace_finished") < keys.index("request_drafted")
    assert _step(t, "trace_finished")["source"] == "case store"
    # both fall in one second: no order is claimed beyond the one a case runs in
    assert _step(t, "request_drafted")["after_previous_s"] == 0.0


def test_the_outcome_step_says_what_the_case_says():
    def named_step(case_id, named):
        t = case_timeline(demo_case(case_id), complaints=[], job=None, opened=[], requests=[],
                          letters_of_request=[], named=named)
        return _step(t, "exchange_named")
    assert named_step("tron-abstain", [])["label"] == "No exchange named: insufficient evidence"
    assert named_step("tron-abstain", [])["detail"] == demo_case("tron-abstain")["abstain_reason"]
    assert named_step("tron-ofac", [])["label"] == \
        "No exchange named: a sanctioned address or a mixer was reached"
    # named by the case, though no request can be drafted on it
    assert named_step("tron-coindcx", [])["label"] == "Exchange named: CoinDCX"
