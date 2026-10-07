"""The portal's signed calls to the tool's half of the contract."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .signing import signed_headers


class ToolClient:
    def __init__(self, base: str, key: str, secret: str, timeout: float = 10.0):
        self.base, self.key, self.secret, self.timeout = base.rstrip("/"), key, secret, timeout

    def call(self, method: str, path: str, body: dict | None = None,
             idempotency: str | None = None) -> tuple[int, dict]:
        """(HTTP status, JSON body). 599 with a sentence when the tool did not answer."""
        raw = json.dumps(body).encode() if body is not None else b""
        headers = signed_headers(self.key, self.secret, method, path, raw)
        if raw:
            headers["Content-Type"] = "application/json"
        if idempotency:
            headers["Idempotency-Key"] = idempotency
        req = urllib.request.Request(self.base + path, data=raw or None, method=method,
                                     headers={"User-Agent": "sahyog-reference-portal/0.1",
                                              **headers})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                status, answer = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, answer = e.code, e.read() or b""
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            return 599, {"detail": f"The tool at {self.base} did not answer "
                                   f"({getattr(e, 'reason', e)})."}
        try:
            parsed = json.loads(answer)
        except ValueError:
            parsed = {"detail": answer.decode("utf-8", "replace")[:300]}
        return status, parsed if isinstance(parsed, dict) else {"detail": str(parsed)[:300]}
