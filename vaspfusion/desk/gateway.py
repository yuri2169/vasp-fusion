"""Where an approved request goes: the `SahyogGateway` interface.

SAHYOG is the I4C portal through which notices reach intermediaries. Its interface
is not public, so this is our side of the contract (docs/sahyog_contract.md): a
gateway is handed the payload and the letter PDF and returns a receipt. The one
implementation, `MockSahyogGateway`, writes both to a local outbox folder. Nothing
leaves the machine, and a real gateway can replace it without touching the desk.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTBOX = ROOT / "data" / "sahyog_outbox"


class GatewayError(RuntimeError):
    """The gateway refused or failed; the request stays unsent."""


class SahyogGateway(Protocol):
    name: str

    def submit(self, payload: dict, pdf: bytes, *, now: datetime) -> dict:
        """Hand over one approved request. Returns the receipt (`GatewayReceipt`):
        gateway, receipt_id, submitted_at, location, payload_sha256. Raises
        GatewayError if the payload is a draft or the submission did not go through."""
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
        rid = payload["request_id"]
        target = self.outbox / f"{rid}.json"
        if target.exists():
            raise GatewayError(f"{rid} is already in the outbox")
        self.outbox.mkdir(parents=True, exist_ok=True)
        body = canonical(payload)
        (self.outbox / f"{rid}.pdf").write_bytes(pdf)
        target.write_bytes(body)
        digest = hashlib.sha256(body).hexdigest()
        return {"gateway": self.name, "receipt_id": f"outbox-{digest[:12]}",
                "submitted_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "location": str(target), "payload_sha256": digest}
