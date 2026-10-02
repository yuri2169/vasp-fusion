"""Login tokens: JWT, HS256 only, standard library only.

A token is `header.payload.signature` (RFC 7519). The header is fixed, and `check`
refuses any token whose header names another algorithm (the "alg: none" and
algorithm-swap forgeries), whose signature does not match, or that has no expiry or
is past it.

The signing secret is `VASPFUSION_JWT_SECRET` (32 characters or more), or else 32
random bytes written once to `data/auth_secret` (mode 0600, git-ignored). It is never
logged or printed.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECRET_FILE = ROOT / "data" / "auth_secret"
HEADER = {"alg": "HS256", "typ": "JWT"}
TTL_S = 8 * 3600                      # one shift
MAX_TOKEN = 4096                      # ours are about 250 characters


class TokenError(ValueError):
    """The token is not one this server issued, or it is no longer valid."""


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as e:
        raise TokenError("not a token") from e


def _sign(signed: bytes, secret: bytes) -> str:
    return _b64(hmac.new(secret, signed, hashlib.sha256).digest())


def issue(claims: dict, secret: bytes, ttl_s: int = TTL_S, now: float | None = None) -> str:
    at = int(time.time() if now is None else now)
    body = {**claims, "iat": at, "exp": at + ttl_s}
    signed = f"{_b64(json.dumps(HEADER, separators=(',', ':')).encode())}." \
             f"{_b64(json.dumps(body, separators=(',', ':')).encode())}"
    return f"{signed}.{_sign(signed.encode(), secret)}"


def check(token: str, secret: bytes, now: float | None = None) -> dict:
    """The claims of a valid token. Raises `TokenError` for anything else."""
    parts = token.split(".") if isinstance(token, str) else []
    if len(parts) != 3 or not all(parts) or len(token) > MAX_TOKEN or not token.isascii():
        raise TokenError("not a token")
    head, body, sig = parts
    try:
        header = json.loads(_unb64(head))
    except (ValueError, RecursionError) as e:
        raise TokenError("not a token") from e
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise TokenError("only HS256 tokens are accepted")
    if not hmac.compare_digest(_sign(f"{head}.{body}".encode(), secret).encode(),
                               sig.encode()):
        raise TokenError("bad signature")
    try:
        claims = json.loads(_unb64(body))
    except (ValueError, RecursionError) as e:
        raise TokenError("not a token") from e
    if not isinstance(claims, dict) or not isinstance(claims.get("exp"), (int, float)):
        raise TokenError("the token has no expiry")
    if (time.time() if now is None else now) >= claims["exp"]:
        raise TokenError("the token has expired")
    return claims


def load_secret(path: Path | str | None = None) -> bytes:
    env = os.environ.get("VASPFUSION_JWT_SECRET", "")
    if env:
        if len(env) < 32:
            raise ValueError("VASPFUSION_JWT_SECRET must be at least 32 characters")
        return env.encode()
    path = Path(path or SECRET_FILE)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        # O_EXCL: two processes starting at once cannot both write a secret
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as f:
                f.write(secrets.token_hex(32))
    secret = path.read_text().strip()
    if len(secret) < 32:                  # an emptied file must not become an empty key
        raise ValueError(f"{path} must hold at least 32 characters; delete it to have a "
                         f"new secret made (everyone signs in again)")
    return secret.encode()
