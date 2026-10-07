"""One timeline per case, built only from what the tool recorded.

Every time on it is read from a record: the complaint store (when the intake took the
complaint), the audit log (an officer opening the case, a letter-of-request draft), the
trace queue (when a worker took the trace and when it closed it), the case store (when a
result was stored, for a case no queue row exists for) and a request's status history.
Nothing is estimated. A step that has not happened is `pending` and has no time; a step
that happened without leaving a record (a case stored from the command line has no
intake or queue row) is `not_recorded` and has no time either.
"""
from __future__ import annotations

from datetime import datetime, timezone

NOTE = ("Every time is read from a record this tool kept (named beside it). A step that "
        "has not happened has no time; none is estimated.")

NOT_NAMED = {"INSUFFICIENT_EVIDENCE": ": insufficient evidence",
             "SANCTIONED_OR_MIXER_REACHED": ": a sanctioned address or a mixer was reached"}
AWAITED = ("sent", "acknowledged")
REPLIES = ("answered", "freeze_confirmed", "refused")
STATUS_LABEL = {
    "drafted": "Request to {vasp} drafted ({ref})",
    "approved": "Request to {vasp} approved ({ref})",
    "sent": "Request to {vasp} sent ({ref})",
    "acknowledged": "{vasp} acknowledged the request ({ref})",
    "answered": "{vasp} answered ({ref})",
    "freeze_confirmed": "Freeze confirmed by {vasp} ({ref})",
    "refused": "{vasp} refused ({ref})",
    "withdrawn": "Request to {vasp} withdrawn ({ref})",
}
PENDING_LABEL = {
    "approved": "Request to {vasp} approved ({ref})",
    "sent": "Request to {vasp} sent ({ref})",
    "acknowledged": "{vasp} acknowledges the request ({ref})",
    "replied": "{vasp} answers, confirms a freeze or refuses ({ref})",
}
# what is still ahead of an open request, by its present status
AHEAD = {"drafted": ("approved", "sent", "acknowledged", "replied"),
         "approved": ("sent", "acknowledged", "replied"),
         "sent": ("acknowledged", "replied"),
         "acknowledged": ("replied",),
         "answered": (), "freeze_confirmed": (), "refused": (), "withdrawn": ()}


def _time(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).replace(microsecond=0)
    if isinstance(value, datetime):
        t = value
    else:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    t = t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
    # The records keep time to different precisions (a request's history to the second,
    # the audit log to the millisecond). Every time is cut to the whole second, so two
    # records are never put in an order their precision cannot support; steps within one
    # second keep the order a case runs in.
    return t.replace(microsecond=0)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def elapsed_words(seconds: float) -> str:
    """14 s; 2 min 30 s; 3 h 2 min; 2 d 1 h."""
    if seconds < 1:
        return "under 1 s"
    s = int(round(seconds))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min" + (f" {s % 60} s" if s % 60 else "")
    if s < 86400:
        return f"{s // 3600} h" + (f" {s % 3600 // 60} min" if s % 3600 // 60 else "")
    return f"{s // 86400} d" + (f" {s % 86400 // 3600} h" if s % 86400 // 3600 else "")


def _step(key: str, label: str, state: str = "done", at: datetime | None = None, *,
          by: str | None = None, via: str | None = None, detail: str | None = None,
          source: str | None = None, request_id: str | None = None) -> dict:
    return {"key": key, "label": label, "state": state, "at": at, "by": by, "via": via,
            "detail": detail, "source": source, "request_id": request_id,
            "after_previous_s": None, "since_first_s": None}


def _trace_steps(case: dict, job: dict | None, named: list[str]) -> list[dict]:
    status = case.get("status")
    steps = []
    if job is None:
        if status != "done":
            return [_step("trace_started", "Trace started", "pending"),
                    _step("trace_finished", "Trace finished", "pending")]
        steps.append(_step("trace_started", "Trace started", "not_recorded",
                           detail="No queue record: the case was stored from the command "
                                  "line, not traced by the server."))
        finished = _time(case.get("created_at"))
        steps.append(_step("trace_finished", "Result stored", at=finished,
                           source="case store"))
    else:
        started = _time(job.get("claimed_at"))
        steps.append(_step("trace_started", "Trace started",
                           "done" if started else "pending", started,
                           source="trace queue" if started else None))
        closed = job.get("state") in ("done", "failed")
        finished = _time(job.get("finished_at")) if closed else None
        source = "trace queue"
        # The result is stored a moment before the queue row is closed. Where the case
        # store holds that earlier time, it is the one shown: a request drafted in
        # between must not read as drafted before the trace finished.
        stored = _time(case.get("created_at")) if status == "done" else None
        if finished and stored and started and started <= stored < finished:
            finished, source = stored, "case store"
        if job.get("state") == "failed":
            steps.append(_step("trace_finished", "Trace failed", at=finished,
                               detail=job.get("error"), source="trace queue"))
            return steps
        seconds = (job.get("stats") or {}).get("seconds")
        steps.append(_step(
            "trace_finished", "Trace finished", "done" if finished else "pending", finished,
            detail=f"The trace itself took {elapsed_words(seconds)}"
            if finished and seconds is not None else None,
            source=source if finished else None))
    if status == "done" and finished is not None:
        # `named` are the exchanges a request can be drafted on; a case can also name
        # one it cannot be drafted on (the wallet is the exchange's own)
        names = named or ([case["top_vasp"]] if case.get("outcome") == "ATTRIBUTED"
                          and case.get("top_vasp") else [])
        if names:
            label = "Exchange named: " + ", ".join(names)
        else:
            label = "No exchange named" + NOT_NAMED.get(case.get("outcome"), "")
        steps.append(_step("exchange_named", label, at=finished,
                           detail=None if names else case.get("abstain_reason"),
                           source=steps[-1]["source"]))
    return steps


def _request_steps(request: dict) -> list[dict]:
    vasp, ref = request["vasp"], request["reference"]
    steps = []
    for i, e in enumerate(request["status_history"]):
        status = e["status"]
        label = STATUS_LABEL[status]
        if status == "drafted" and i:
            label = "Request to {vasp} sent back to draft ({ref})"
        steps.append(_step(f"request_{status}", label.format(vasp=vasp, ref=ref),
                           at=_time(e["at"]), by=e.get("by"), via=e.get("via"),
                           detail=e.get("note"), source="request history",
                           request_id=request["id"]))
    for ahead in AHEAD[request["status"]]:
        steps.append(_step(f"request_{ahead}", PENDING_LABEL[ahead].format(vasp=vasp, ref=ref),
                           "pending", request_id=request["id"]))
    return steps


def case_timeline(case: dict, *, complaints: list[dict], job: dict | None,
                  opened: list[dict], requests: list[dict],
                  letters_of_request: list[dict], named: list[str]) -> dict:
    """`CaseTimeline`. `complaints` are the stored complaints that reported this case's
    wallet; `job` its row in the trace queue; `opened` the audit rows of an officer
    opening it; `requests` the stored requests that list it; `letters_of_request` the
    audit rows of a letter-of-request draft made for it; `named` the exchanges a request
    can be drafted on."""
    steps: list[dict] = []
    for c in complaints:
        steps.append(_step("complaint_received", "Complaint received through the intake",
                           at=_time(c["received_at"]), via="sahyog",
                           detail=c["complaint_ref"], source="complaint store"))
    for row in opened[:1]:               # the first time an officer opened it
        steps.append(_step("case_opened", "Case opened by an officer", at=_time(row["at"]),
                           by=row.get("officer"), source="audit log"))
    if not steps:
        steps.append(_step("case_opened", "Case opened", "not_recorded",
                           detail="No complaint and no audit row records how this case "
                                  "was opened."))
    steps += _trace_steps(case, job, named)
    for row in letters_of_request:
        steps.append(_step(
            "letter_of_request_drafted", f"Letter-of-request draft for {row['target']} made",
            at=_time(row["at"]), by=row.get("officer"), source="audit log",
            detail="A draft for the officer and the Court. Not sent by this tool."))
    asked = set()
    for r in sorted(requests, key=lambda r: (str(r["status_history"][0]["at"]), r["id"])):
        steps += _request_steps(r)
        if r["status"] != "withdrawn":
            asked.add(r["vasp"])
    if case.get("status") == "done":
        for vasp in named:
            if vasp not in asked:
                steps.append(_step("request_drafted", f"Request to {vasp}: not drafted",
                                   "pending"))

    timed = sorted((s for s in steps if s["at"] is not None), key=lambda s: s["at"])
    for prev, s in zip([None] + timed, timed):       # the sort is stable: ties keep order
        s["since_first_s"] = round((s["at"] - timed[0]["at"]).total_seconds(), 1)
        if prev is not None:
            s["after_previous_s"] = round((s["at"] - prev["at"]).total_seconds(), 1)
    ordered = ([s for s in steps if s["state"] == "not_recorded"] + timed
               + [s for s in steps if s["state"] == "pending"])
    for s in ordered:
        s["at"] = _iso(s["at"]) if s["at"] else None
    return {"steps": ordered, "note": NOTE}
