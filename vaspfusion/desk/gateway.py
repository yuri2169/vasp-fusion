"""What crosses between this tool and SAHYOG: the `SahyogGateway` interface.

SAHYOG is the I4C portal through which notices reach intermediaries. Its interface
is not public, so this is our side of the contract (docs/sahyog_contract.md). Three
things pass through a gateway: an approved request goes out (`submit`), the result of
a complaint's trace goes back (`notify_result`), and an exchange's reply comes in
(`record_reply`). `MockSahyogGateway`, the default, writes each to a local outbox
folder and nothing leaves the machine. `HttpSahyogGateway` (chosen by SAHYOG_URL) makes
signed HTTPS calls to a portal that implements the other half of the contract; the one
portal that does so today is the reference portal in this repository (refportal/).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import urlsplit

from . import signing

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


RETRY = (429, 502, 503, 504, 599)       # 599: no answer at all (chains/http.py)
LOOPBACK = ("localhost", "127.0.0.1", "::1")


class HttpSahyogGateway:
    """Signed calls to a portal's half of the contract (docs/sahyog_contract.md, 5).

    Every call carries the API key, a timestamp, a nonce and an HMAC over them and the
    body (signing.py), and an Idempotency-Key, so a retry after a lost answer is not a
    second submission. A call that gets no answer, or 429 / 502 / 503 / 504, is tried
    again after a pause; when the tries run out a GatewayError says which host did not
    answer and why, and the desk leaves the request approved and unsent. What was
    accepted is also kept in the local outbox, so the letter can be served as sent.
    """
    name = "sahyog-http"

    def __init__(self, url: str, key: str | None, secret: str | None, *,
                 journal: MockSahyogGateway, transport=None, tries: int = 3,
                 timeout: float = 10.0, backoff: float = 0.5, allow_http: bool = False,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        parts = urlsplit(url.strip())
        self.base, self.host = url.strip().rstrip("/"), parts.netloc
        self.prefix = parts.path.rstrip("/")
        self.key, self.secret, self.journal = key, secret, journal
        self.tries, self.timeout, self.backoff = max(1, tries), timeout, backoff
        self.sleep, self.clock = sleep, clock
        self._transport = transport
        self.problem = None
        if parts.scheme not in ("http", "https") or not parts.hostname:
            self.problem = "SAHYOG_URL is not an http(s) address"
        elif parts.scheme != "https" and not allow_http and parts.hostname not in LOOPBACK:
            self.problem = (f"SAHYOG_URL ({self.host}) is not https; a plain-http portal is "
                            "accepted only on this machine or with SAHYOG_ALLOW_HTTP=1")
        elif not key:
            self.problem = "no API key is set for the portal (SAHYOG_API_KEY)"
        elif not secret:
            self.problem = "no signing secret is set for the portal (SAHYOG_SIGNING_SECRET)"

    @property
    def transport(self):
        if self._transport is None:
            from ..chains.http import UrllibTransport
            self._transport = UrllibTransport(self.timeout)
        return self._transport

    def _call(self, method: str, path: str, body: bytes, idempotency: str | None) -> dict:
        """One signed call, retried. Returns the JSON answer of a 2xx."""
        if self.problem:
            raise GatewayError(f"the portal is not configured: {self.problem}")
        status, raw = 599, b""
        for attempt in range(self.tries):
            if attempt:
                self.sleep(self.backoff * 2 ** (attempt - 1))
            # signed afresh each time: the portal refuses a nonce it has seen
            headers = signing.headers(self.key, self.secret, method, self.prefix + path, body,
                                      now=self.clock())
            if body:
                headers["Content-Type"] = "application/json"
            if idempotency:
                headers[signing.IDEMPOTENCY_HEADER] = idempotency
            status, raw = self.transport.send(method, self.base + path, body or None, headers,
                                              self.timeout)
            if status not in RETRY:
                break
        said = _said(raw)
        if status in RETRY:
            why = f"no answer ({said})" if status == 599 else f"HTTP {status}"
            raise GatewayError(f"the portal at {self.host} could not be reached after "
                               f"{self.tries} tries: {why}")
        if not 200 <= status < 300:
            raise GatewayError(f"the portal at {self.host} refused the call (HTTP {status}): "
                               f"{said}")
        try:
            answer = json.loads(raw)
        except ValueError:
            answer = None
        if not isinstance(answer, dict):
            raise GatewayError(f"the portal at {self.host} answered something that is not "
                               "a receipt")
        return answer

    def _receipt(self, answer: dict, digest: str, path: str, now: datetime) -> dict:
        if answer.get("payload_sha256") != digest:
            raise GatewayError(f"the portal at {self.host} acknowledged a different payload "
                               "than the one sent")
        return {"gateway": self.name, "receipt_id": str(answer.get("receipt_id"))[:100],
                "submitted_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "location": f"{self.host}{self.prefix}{path}", "payload_sha256": digest}

    def health(self) -> dict:
        """What the portal says of itself (GET /v1/health). Raises GatewayError."""
        return self._call("GET", "/v1/health", b"", None)

    def submit(self, payload: dict, pdf: bytes, *, now: datetime) -> dict:
        if payload.get("draft") is not False:
            raise GatewayError("a draft cannot be submitted: the request must be approved")
        rid = str(payload.get("request_id"))
        if not _ID.match(rid):
            raise GatewayError(f"{rid!r} is not a request id")
        digest = hashlib.sha256(canonical(payload)).hexdigest()
        body = canonical({"payload": payload,
                          "letter_pdf_b64": base64.b64encode(pdf).decode()})
        answer = self._call("POST", "/v1/requests", body, f"request:{rid}:{digest[:16]}")
        receipt = self._receipt(answer, digest, f"/v1/requests/{rid}", now)
        self.journal.submit(payload, pdf, now=now)      # the local copy of what was sent
        return receipt

    def sent_pdf(self, request_id: str) -> bytes | None:
        return self.journal.sent_pdf(request_id)

    def notify_result(self, payload: dict, *, now: datetime) -> dict:
        digest = hashlib.sha256(canonical(payload)).hexdigest()
        case = (payload.get("wallet") or {}).get("case_id")
        answer = self._call("POST", "/v1/results", canonical(payload),
                            f"result:{payload.get('complaint_ref')}:{case}:{digest[:16]}")
        receipt = self._receipt(answer, digest, "/v1/results", now)
        self.journal.notify_result(payload, now=now)
        return receipt

    def record_reply(self, request_id: str, reply: dict, *, now: datetime) -> dict:
        """The reply came from the portal; it is kept here as it arrived."""
        return {**self.journal.record_reply(request_id, reply, now=now), "gateway": self.name}


def _said(raw: bytes) -> str:
    try:
        body = json.loads(raw)
        text = body.get("detail") if isinstance(body, dict) else None
    except ValueError:
        text = None
    return str(text or raw.decode("utf-8", "replace")).strip()[:200] or "no body"


def gateway_from_env(outbox: Path | str | None = None, key_file: Path | str | None = None,
                     secret_file: Path | str | None = None) -> SahyogGateway:
    """The gateway this installation is configured for: the HTTP one when SAHYOG_URL is
    set, else the mock outbox."""
    from .intake import configured_key, configured_secret
    journal = MockSahyogGateway(outbox)
    url = os.environ.get("SAHYOG_URL", "").strip()
    if not url:
        return journal
    return HttpSahyogGateway(
        url, configured_key(key_file), configured_secret(secret_file), journal=journal,
        tries=int(os.environ.get("SAHYOG_TRIES") or 3),
        timeout=float(os.environ.get("SAHYOG_TIMEOUT") or 10),
        allow_http=os.environ.get("SAHYOG_ALLOW_HTTP", "") == "1")
