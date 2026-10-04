"""What crosses between this tool and SAHYOG: the `SahyogGateway` interface.

SAHYOG is the I4C portal through which notices reach intermediaries. Its interface
is not public, so this is our side of the contract (docs/sahyog_contract.md). Three
things pass through a gateway: an approved request goes out (`submit`), the result of
a complaint's trace goes back (`notify_result`), and an exchange's reply comes in
(`record_reply`). The one implementation, `MockSahyogGateway`, writes each to a local
outbox folder. Nothing leaves the machine, and a real gateway can replace it without
touching the desk or the intake.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTBOX = ROOT / "data" / "sahyog_outbox"
_ID = re.compile(r"^req-\d{4}-\d{4,}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class GatewayError(RuntimeError):
    """The gateway refused or failed; the request stays unsent."""


class SahyogGateway(Protocol):
    name: str

    def submit(self, payload: dict, pdf: bytes, *, now: datetime) -> dict:
        """Hand over one approved request. Returns the receipt (`GatewayReceipt`):
        gateway, receipt_id, submitted_at, location, payload_sha256. Raises
        GatewayError if the payload is a draft or the submission did not go through.
        Submitting the very same payload and letter again must succeed (the caller may
        have failed after the first submission) and must not send it twice."""
        ...

    def sent_pdf(self, request_id: str) -> bytes | None:
        """The letter exactly as it was submitted, or None if the gateway keeps none."""
        ...

    def notify_result(self, payload: dict, *, now: datetime) -> dict:
        """Hand back the result of one wallet of a complaint (`vaspfusion-sahyog-result/1`).
        Returns a receipt: gateway, receipt_id, submitted_at, location, payload_sha256.
        Handing over the same wallet again replaces what was handed over before."""
        ...

    def record_reply(self, request_id: str, reply: dict, *, now: datetime) -> dict:
        """Keep an exchange's reply to a sent request as it arrived
        (`vaspfusion-sahyog-reply/1`). Returns a receipt as above."""
        ...


def canonical(payload: dict) -> bytes:
    """The bytes a payload is hashed and written as: sorted keys, UTF-8, one line."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode()


class MockSahyogGateway:
    """Writes `<request_id>.json` and `<request_id>.pdf` to the outbox. Sends nothing."""
    name = "mock-outbox"

    def __init__(self, outbox: Path | str | None = None):
        self.outbox = Path(outbox or os.environ.get("VASPFUSION_SAHYOG_OUTBOX")
                           or DEFAULT_OUTBOX)

    def submit(self, payload: dict, pdf: bytes, *, now: datetime) -> dict:
        if payload.get("draft") is not False:
            raise GatewayError("a draft cannot be submitted: the request must be approved")
        rid = str(payload.get("request_id"))
        if not _ID.match(rid):
            raise GatewayError(f"{rid!r} is not a request id")
        target, letter = self.outbox / f"{rid}.json", self.outbox / f"{rid}.pdf"
        body = canonical(payload)
        if target.exists():
            if target.read_bytes() != body or not letter.exists() or letter.read_bytes() != pdf:
                raise GatewayError(f"{rid} is already in the outbox with different contents")
        else:
            self.outbox.mkdir(parents=True, exist_ok=True)
            letter.write_bytes(pdf)
            target.write_bytes(body)
        digest = hashlib.sha256(body).hexdigest()
        return {"gateway": self.name, "receipt_id": f"outbox-{digest[:12]}",
                "submitted_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "location": f"{self.outbox.name}/{target.name}", "payload_sha256": digest}

    def sent_pdf(self, request_id: str) -> bytes | None:
        letter = self.outbox / f"{request_id}.pdf"
        return letter.read_bytes() if _ID.match(request_id) and letter.exists() else None

    def _keep(self, folder: str, name: str, payload: dict, now: datetime) -> dict:
        if not _NAME.match(name):
            raise GatewayError(f"{name!r} cannot be a file name")
        target = self.outbox / folder / f"{name}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        body = canonical(payload)
        target.write_bytes(body)
        digest = hashlib.sha256(body).hexdigest()
        return {"gateway": self.name, "receipt_id": f"outbox-{digest[:12]}",
                "submitted_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "location": f"{self.outbox.name}/{folder}/{target.name}",
                "payload_sha256": digest}

    def notify_result(self, payload: dict, *, now: datetime) -> dict:
        """Writes `results/<complaint_ref>__<case_id>.json`. The callback URL in the
        payload is never called: nothing leaves the machine."""
        name = f"{payload.get('complaint_ref')}__{(payload.get('wallet') or {}).get('case_id')}"
        return self._keep("results", name, payload, now)

    def record_reply(self, request_id: str, reply: dict, *, now: datetime) -> dict:
        """Writes `replies/<request_id>.<status>.json`."""
        if not _ID.match(request_id) or not (self.outbox / f"{request_id}.json").exists():
            raise GatewayError(f"{request_id} was never submitted through this gateway")
        return self._keep("replies", f"{request_id}.{reply.get('status')}", reply, now)
