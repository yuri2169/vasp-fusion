"""The contract's signing scheme (docs/sahyog_contract.md, section 1), written here
from the document and not shared with the tool, so that the two programs agreeing is a
test of the contract."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

WINDOW_S = 300


class Refused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def sign(secret: str, timestamp: str, nonce: str, method: str, path: str, body: bytes) -> str:
    message = f"v1\n{timestamp}\n{nonce}\n{method.upper()}\n{path}\n" \
        + hashlib.sha256(body).hexdigest()
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def signed_headers(key: str, secret: str, method: str, path: str, body: bytes) -> dict:
    timestamp, nonce = str(int(time.time())), secrets.token_urlsafe(18)
    return {"X-SAHYOG-Key": key, "X-SAHYOG-Timestamp": timestamp, "X-SAHYOG-Nonce": nonce,
            "X-SAHYOG-Signature": "v1=" + sign(secret, timestamp, nonce, method, path, body)}


def check(key: str, secret: str, headers, method: str, path: str, body: bytes) -> str:
    """Refuse a call whose key, signature or timestamp is wrong. Returns the nonce."""
    given = headers.get("x-sahyog-key") or ""
    if not hmac.compare_digest(given.encode(), key.encode()):
        raise Refused(401, "The X-SAHYOG-Key header is missing or wrong.")
    timestamp = headers.get("x-sahyog-timestamp") or ""
    nonce = headers.get("x-sahyog-nonce") or ""
    signature = headers.get("x-sahyog-signature") or ""
    if not (timestamp.isdigit() and 16 <= len(nonce) <= 128 and signature):
        raise Refused(401, "The call is not signed.")
    want = "v1=" + sign(secret, timestamp, nonce, method, path, body)
    if not hmac.compare_digest(signature.encode(), want.encode()):
        raise Refused(401, "The X-SAHYOG-Signature header does not match the call.")
    if abs(time.time() - int(timestamp)) > WINDOW_S:
        raise Refused(401, f"The X-SAHYOG-Timestamp header is more than {WINDOW_S} seconds "
                           "from this server's clock.")
    return nonce
