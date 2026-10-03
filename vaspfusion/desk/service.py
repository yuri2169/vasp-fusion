"""The request desk: draft, review, send, track.

One consolidated request per exchange. A request is drafted from finished cases,
must be approved by the officer before it can be sent, and is sent through a
`SahyogGateway`. Its status then follows what the exchange does:

    drafted -> approved -> sent -> acknowledged -> answered | freeze_confirmed | refused
    drafted | approved -> withdrawn      (a draft made by mistake; its wallets are open again)

The letter and the payload are fixed when the request is drafted. Only the status,
the watermark, the due date and (once sent) the receipt change afterwards. A request
whose case has since been traced again with a different result cannot be approved or
sent: it has to be withdrawn and drafted afresh.
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..cases import CODE_VERSION
from .directory import Directory
from .gateway import GatewayError, SahyogGateway
from .letter import ASK_ORDER, WATERMARK, build_payload, draft_letter
from .pdf import letter_pdf
from .routing import UNROUTABLE, build_desk, routable, routed_wallets, vasp_detail

TRANSITIONS: dict[str, tuple[str, ...]] = {
    "drafted": ("approved", "withdrawn"),
    "approved": ("sent", "drafted", "withdrawn"),
    "sent": ("acknowledged", "answered", "freeze_confirmed", "refused"),
    "acknowledged": ("answered", "freeze_confirmed", "refused"),
    "answered": ("freeze_confirmed",),
    "freeze_confirmed": (),
    "refused": (),
    "withdrawn": (),
}
# a wallet in a request with one of these statuses cannot be put in another request
BLOCKING = ("drafted", "approved", "sent", "acknowledged", "answered", "freeze_confirmed")

# One server process is assumed, as everywhere in this single-workstation tool: drafting
# and status changes queue here, so two clicks cannot both act on the same stored state.
_LOCK = threading.RLock()


@dataclass(frozen=True)
class DeskConfig:
    # Days after sending when the desk starts reminding. An office setting, not a
    # period set by law: no statute read for this phase fixes a reply time.
    reply_days: int = 7


class DeskError(Exception):
    """A request that cannot be made or moved. `status` is the HTTP status it maps to:
    404 unknown, 409 not allowed from the current state, 422 not supported by the
    evidence, 502 the gateway failed."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(text: str, limit: int) -> str:
    return " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())[:limit]


def _event(status: str, at: datetime, note: str | None, by: str | None) -> dict:
    """A status-history entry. `by` is there only when a signed-in officer made it."""
    event = {"status": status, "at": _iso(at), "note": note}
    return {**event, "by": by} if by else event


class DeskService:
    def __init__(self, cases, requests, directory: Directory, gateway: SahyogGateway,
                 cfg: DeskConfig = DeskConfig(),
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.cases, self.requests, self.directory = cases, requests, directory
        self.gateway, self.cfg, self.now = gateway, cfg, now

    # ------------------------------------------------------------------ reads
    def _all_cases(self) -> list[dict]:
        return [self.cases.get(c["id"]) for c in self.cases.list(status="done")]

    def _routed(self, case: dict, vasp: str) -> list[dict]:
        return [w for w in routed_wallets(case, canonical=self.directory.canonical)
                if w["vasp"] == vasp]

    def desk(self) -> dict:
        return build_desk(self._all_cases(), self.requests.list(), self.now().date(),
                          canonical=self.directory.canonical)

    def vasp(self, name: str, label_counts: dict[str, int]) -> dict:
        return vasp_detail(name, self.directory, label_counts, self._all_cases(),
                           self.requests.list())

    def get(self, request_id: str) -> dict | None:
        req = self.requests.get(request_id)
        return self._view(req) if req else None

    def list(self) -> list[dict]:
        """Every request, newest first, as `get` gives each."""
        return [self._view(req) for req in self.requests.list()]

    def pdf(self, request_id: str) -> bytes:
        """The letter. Once sent, the very bytes that were submitted (while the gateway
        still holds them and they match the recorded hash); otherwise rendered now."""
        req = self.requests.get(request_id)
        if req is None:
            raise DeskError(404, f"No request {request_id}.")
        if req.get("receipt"):
            sent = self.gateway.sent_pdf(request_id)
            if sent is not None and hashlib.sha256(sent).hexdigest() == \
                    req["payload"]["documents"][0]["sha256"]:
                return sent
        return letter_pdf(req, req["payload"]["generated_by"]["code_version"])

    @staticmethod
    def _view(req: dict) -> dict:
        return {**req, "allowed_next": list(TRANSITIONS[req["status"]])}

    # ------------------------------------------------------------------ draft
    def create(self, vasp: str, case_ids: list[str], asks: list[str], officer: str,
               wallets: list[str] | None = None, by: str | None = None) -> dict:
        """`officer` is the name printed on the letter; `by` is the signed-in account that
        drafted it (None when no login is in force)."""
        with _LOCK:
            return self._view(self._create(vasp, case_ids, asks, officer, wallets, by))

    def _create(self, vasp, case_ids, asks, officer, wallets, by=None) -> dict:
        vasp = self.directory.canonical(_clean(vasp, 100))
        officer = _clean(officer, 200)
        if not officer:
            raise DeskError(422, "Name the officer making the request.")
        try:
            officer.encode("cp1252")
        except UnicodeEncodeError:
            raise DeskError(422, "Write the officer's name and post in Latin letters: the "
                                 "letter's typeface cannot print other scripts.") from None
        if vasp == UNROUTABLE:
            raise DeskError(422, "The source tags this address as an exchange but names no "
                                 "owner, so there is no one to address a request to.")
        asks = [a for a in ASK_ORDER if a in asks]
        if not asks:
            raise DeskError(422, "Choose at least one thing to ask for.")
        found: list[dict] = []
        for cid in dict.fromkeys(case_ids):
            case = self.cases.get(cid)
            if case is None:
                raise DeskError(404, f"No case {cid}.")
            if case.get("status") != "done":
                raise DeskError(409, f"Case {cid} has not finished tracing.")
            mine = self._routed(case, vasp)
            if not mine:
                raise DeskError(422, f"Case {cid} does not support a request to {vasp}: "
                                     f"{self._why_not(case, vasp)}.")
            found += mine

        asked = {(w.get("case_id"), w["address"]): r["id"]
                 for r in self.requests.list(vasp=vasp) if r["status"] in BLOCKING
                 for w in r["letter"]["wallets"]}
        if wallets is not None:
            known = {w["address"] for w in found}
            unknown = [a for a in wallets if a not in known]
            if unknown:
                raise DeskError(422, f"{unknown[0]} is not a wallet these cases route to {vasp}.")
            found = [w for w in found if w["address"] in set(wallets)]
            if not found:
                raise DeskError(422, "Choose at least one wallet.")
            taken = [w for w in found if (w["case_id"], w["address"]) in asked]
            if taken:
                w = taken[0]
                raise DeskError(409, f"{w['address']} is already asked about in "
                                     f"{asked[(w['case_id'], w['address'])]}.")
        else:       # the default: every wallet not yet asked about
            fresh = [w for w in found if (w["case_id"], w["address"]) not in asked]
            if not fresh:
                raise DeskError(409, f"Every wallet these cases route to {vasp} is already "
                                     f"asked about in {', '.join(sorted(set(asked.values())))}.")
            found = fresh

        now = self.now()
        rid, reference = self.requests.next_id(now.year)
        entry = self.directory.get(vasp)
        letter = draft_letter(reference=reference, vasp=vasp, entry=entry, wallets=found,
                              asks=asks, officer=officer, today=now.date())
        request = {
            "id": rid, "reference": reference, "vasp": vasp, "status": "drafted",
            "case_ids": [c["case_id"] for c in letter["cases"]], "created_at": _iso(now),
            "due": None,
            "status_history": [_event("drafted", now, f"Drafted by {officer}", by)],
            "letter": letter, "pdf_url": f"/api/requests/{rid}/pdf",
            "payload": build_payload(request_id=rid, created_at=now, vasp=vasp, entry=entry,
                                     letter=letter, code_version=CODE_VERSION),
            "receipt": None,
        }
        self.requests.save(request)
        return request

    def _why_not(self, case: dict, vasp: str) -> str:
        cands = [c for c in case.get("candidates", [])
                 if self.directory.canonical(c["vasp"]) == vasp]
        outbound = [c for c in cands if c["direction"] == "outbound"]
        if not cands:
            return f"it does not reach {vasp}"
        if not outbound:
            return f"{vasp} only funded the wallet; ask it which account withdrew"
        best = max(outbound, key=lambda c: c["confidence"])
        if best["hops"] == 0:
            return (f"the wallet is {vasp}'s own; ask {vasp} about the transfers of "
                    "interest directly")
        if not routable({**best, "request_wallets": [1]}):
            return (f"it reaches {vasp} only with confidence {best['confidence']:.2f}, "
                    "under the 0.60 needed to name an exchange")
        return ("the case was stored before the desk existed and does not say which "
                "wallets to ask about; trace it again")

    def _still_supported(self, req: dict) -> None:
        """A request may only go forward if every wallet in it is still what its case
        says: the case may have been traced again since the draft."""
        for w in req["letter"]["wallets"]:
            case = self.cases.get(w["case_id"]) if w.get("case_id") else None
            now = [r for r in (self._routed(case, req["vasp"]) if case else [])
                   if (r["address"], r["paid_into"]) == (w["address"], w.get("paid_into"))]
            if not now or now[0]["amount"] != w["amount"] or now[0]["tier"] != w["tier"]:
                raise DeskError(409, (
                    f"Case {w.get('case_id')} no longer supports this request for "
                    f"{w['address']}: it was traced again or removed since the draft. "
                    "Withdraw this request and draft a new one."))

    # ------------------------------------------------------------------ status
    def patch(self, request_id: str, status: str, note: str | None = None,
              by: str | None = None) -> dict:
        with _LOCK:
            return self._view(self._patch(request_id, status, note, by))

    def _patch(self, request_id: str, status: str, note: str | None,
               by: str | None = None) -> dict:
        req = self.requests.get(request_id)
        if req is None:
            raise DeskError(404, f"No request {request_id}.")
        allowed = TRANSITIONS[req["status"]]
        if status not in allowed:
            raise DeskError(409, f"A request that is {req['status']} cannot become {status}. "
                            + (f"Next: {' or '.join(allowed)}." if allowed
                               else "It is closed."))
        if status in ("approved", "sent"):
            self._still_supported(req)
        now = self.now()
        note = _clean(note, 500) if note else None
        req["letter"]["watermark"] = WATERMARK if status in ("drafted", "withdrawn") else None
        req["payload"]["draft"] = req["letter"]["watermark"] is not None
        if status == "sent":
            pdf = letter_pdf(req, req["payload"]["generated_by"]["code_version"])
            req["payload"]["documents"] = [{
                "name": f"{req['id']}.pdf", "media_type": "application/pdf",
                "sha256": hashlib.sha256(pdf).hexdigest()}]
            try:
                req["receipt"] = self.gateway.submit(req["payload"], pdf, now=now)
            except GatewayError as e:
                raise DeskError(502, f"Not sent: {e}.") from e
            req["due"] = (now.date() + timedelta(days=self.cfg.reply_days)).isoformat()
            sent = (f"Written to the SAHYOG outbox ({self.gateway.name}); nothing left this "
                    "machine" if self.gateway.name == "mock-outbox"
                    else f"Submitted through {self.gateway.name}") \
                + f", receipt {req['receipt']['receipt_id']}"
            note = f"{note}. {sent}" if note else sent
        req["status"] = status
        req["status_history"].append(_event(status, now, note, by))
        self.requests.save(req)
        return req
