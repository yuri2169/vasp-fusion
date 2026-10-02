"""The request desk: draft, review, send, track.

One consolidated request per exchange. A request is drafted from finished cases,
must be approved by the officer before it can be sent, and is sent through a
`SahyogGateway`. Its status then follows what the exchange does:

    drafted -> approved -> sent -> acknowledged -> answered | freeze_confirmed | refused

The letter and the payload are fixed when the request is drafted. Only the status,
the watermark, the due date and (once sent) the receipt change afterwards.
"""
from __future__ import annotations

import hashlib
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
    "drafted": ("approved",),
    "approved": ("sent", "drafted"),
    "sent": ("acknowledged", "answered", "freeze_confirmed", "refused"),
    "acknowledged": ("answered", "freeze_confirmed", "refused"),
    "answered": ("freeze_confirmed",),
    "freeze_confirmed": (),
    "refused": (),
}


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


class DeskService:
    def __init__(self, cases, requests, directory: Directory, gateway: SahyogGateway,
                 cfg: DeskConfig = DeskConfig(),
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.cases, self.requests, self.directory = cases, requests, directory
        self.gateway, self.cfg, self.now = gateway, cfg, now

    # ------------------------------------------------------------------ reads
    def _all_cases(self) -> list[dict]:
        return [self.cases.get(c["id"]) for c in self.cases.list(status="done")]

    def desk(self) -> dict:
        return build_desk(self._all_cases(), self.requests.list(), self.now().date())

    def vasp(self, name: str, label_counts: dict[str, int]) -> dict:
        return vasp_detail(name, self.directory, label_counts, self._all_cases(),
                           self.requests.list())

    def knows(self, name: str) -> bool:
        """Is this exchange in the directory, a case, or a request?"""
        vasp = self.directory.canonical(name)
        return (vasp in self.directory.names()
                or any(r["vasp"] == vasp for r in self.requests.list())
                or any(c["vasp"] == vasp for case in self._all_cases()
                       for c in case.get("candidates", [])))

    def get(self, request_id: str) -> dict | None:
        req = self.requests.get(request_id)
        return self._view(req) if req else None

    def pdf(self, request_id: str) -> bytes:
        req = self.requests.get(request_id)
        if req is None:
            raise DeskError(404, f"No request {request_id}.")
        return letter_pdf(req, req["payload"]["generated_by"]["code_version"])

    @staticmethod
    def _view(req: dict) -> dict:
        return {**req, "allowed_next": list(TRANSITIONS[req["status"]])}

    # ------------------------------------------------------------------ draft
    def create(self, vasp: str, case_ids: list[str], asks: list[str], officer: str,
               wallets: list[str] | None = None) -> dict:
        vasp = self.directory.canonical(vasp.strip())
        officer = " ".join(officer.split())[:200]
        if not officer:
            raise DeskError(422, "Name the officer making the request.")
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
            mine = [w for w in routed_wallets(case) if w["vasp"] == vasp]
            if not mine:
                under = [c for c in case.get("candidates", [])
                         if c["vasp"] == vasp and not routable(c)]
                why = (f"it reaches {vasp} only with confidence "
                       f"{max(c['confidence'] for c in under):.2f}, under the 0.60 needed to "
                       "name an exchange" if any(c["direction"] == "outbound" for c in under)
                       else f"{vasp} only funded the wallet; ask it which account withdrew"
                       if under else f"it does not reach {vasp}")
                raise DeskError(422, f"Case {cid} does not support a request to {vasp}: {why}.")
            found += mine
        if wallets is not None:
            known = {w["address"] for w in found}
            unknown = [a for a in wallets if a not in known]
            if unknown:
                raise DeskError(422, f"{unknown[0]} is not a wallet these cases route to {vasp}.")
            found = [w for w in found if w["address"] in set(wallets)]
            if not found:
                raise DeskError(422, "Choose at least one wallet.")

        now = self.now()
        rid, reference = self.requests.next_id(now.year)
        entry = self.directory.get(vasp)
        letter = draft_letter(reference=reference, vasp=vasp, entry=entry, wallets=found,
                              asks=asks, officer=officer, today=now.date())
        request = {
            "id": rid, "reference": reference, "vasp": vasp, "status": "drafted",
            "case_ids": [c["case_id"] for c in letter["cases"]], "created_at": _iso(now),
            "due": None,
            "status_history": [{"status": "drafted", "at": _iso(now),
                                "note": f"Drafted by {officer}"}],
            "letter": letter, "pdf_url": f"/api/requests/{rid}/pdf",
            "payload": build_payload(request_id=rid, created_at=now, vasp=vasp, entry=entry,
                                     letter=letter, code_version=CODE_VERSION),
            "receipt": None,
        }
        self.requests.save(request)
        return self._view(request)

    # ------------------------------------------------------------------ status
    def patch(self, request_id: str, status: str, note: str | None = None) -> dict:
        req = self.requests.get(request_id)
        if req is None:
            raise DeskError(404, f"No request {request_id}.")
        allowed = TRANSITIONS[req["status"]]
        if status not in allowed:
            raise DeskError(409, f"A request that is {req['status']} cannot become {status}. "
                            + (f"Next: {' or '.join(allowed)}." if allowed
                               else "It is closed."))
        now = self.now()
        note = " ".join(note.split())[:500] if note else None
        req["letter"]["watermark"] = WATERMARK if status == "drafted" else None
        req["payload"]["draft"] = status == "drafted"
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
        req["status_history"].append({"status": status, "at": _iso(now), "note": note})
        self.requests.save(req)
        return self._view(req)
