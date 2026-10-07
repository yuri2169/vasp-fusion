"""Signed calls between this tool and the portal (docs/sahyog_contract.md, section 1).

Every call carries a timestamp, a nonce and an HMAC-SHA256 over them, the method, the
path and the SHA-256 of the body. The receiver refuses a signature that does not match,
a timestamp too far from its own clock, and (the caller of `verify` does this, with a
store) a nonce it has seen before. The secret is shared out of band and is never sent.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime

KEY_HEADER = "X-SAHYOG-Key"
TIMESTAMP_HEADER = "X-SAHYOG-Timestamp"
NONCE_HEADER = "X-SAHYOG-Nonce"
SIGNATURE_HEADER = "X-SAHYOG-Signature"
IDEMPOTENCY_HEADER = "Idempotency-Key"
VERSION = "v1"
WINDOW_S = 300


class SignatureError(Exception):
    """A call that is not what its signature says. `status` is the HTTP status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def sign(secret: str, timestamp: str, nonce: str, method: str, path: str, body: bytes) -> str:
    """The hex signature. `path` is the path with its query string, as sent."""
    text = "\n".join((VERSION, timestamp, nonce, method.upper(), path,
                      hashlib.sha256(body).hexdigest()))
    return hmac.new(secret.encode(), text.encode(), hashlib.sha256).hexdigest()


def headers(key: str, secret: str, method: str, path: str, body: bytes, *, now: datetime,
            nonce: str | None = None) -> dict[str, str]:
    """The four headers of one signed call."""
    timestamp = str(int(now.timestamp()))
    nonce = nonce or secrets.token_urlsafe(18)
    return {KEY_HEADER: key, TIMESTAMP_HEADER: timestamp, NONCE_HEADER: nonce,
            SIGNATURE_HEADER: f"{VERSION}={sign(secret, timestamp, nonce, method, path, body)}"}


def verify(secret: str, given: dict, method: str, path: str, body: bytes, *, now: datetime,
           window: int = WINDOW_S) -> str:
    """Check the signature and the timestamp of a received call; returns its nonce, which
    the caller must then refuse if it was seen before. `given` maps lower-case header
    names to values."""
    timestamp = given.get(TIMESTAMP_HEADER.lower(), "")
    nonce = given.get(NONCE_HEADER.lower(), "")
    signature = given.get(SIGNATURE_HEADER.lower(), "")
    if not (timestamp and nonce and signature):
        raise SignatureError(401, "The call is not signed: "
                                  f"{TIMESTAMP_HEADER}, {NONCE_HEADER} and "
                                  f"{SIGNATURE_HEADER} are required.")
    if not timestamp.isdigit() or not 16 <= len(nonce) <= 128:
        raise SignatureError(401, f"The {TIMESTAMP_HEADER} or {NONCE_HEADER} header is "
                                  "malformed.")
    want = f"{VERSION}={sign(secret, timestamp, nonce, method, path, body)}"
    if not hmac.compare_digest(signature.encode(), want.encode()):
        raise SignatureError(401, f"The {SIGNATURE_HEADER} header does not match the call.")
    if abs(int(now.timestamp()) - int(timestamp)) > window:
        raise SignatureError(401, f"The {TIMESTAMP_HEADER} header is more than {window} "
                                  "seconds from this server's clock.")
    return nonce
