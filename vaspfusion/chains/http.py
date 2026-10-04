"""HTTP transport and API-key loading. The only module that opens sockets.

Keys (TRONGRID_API_KEY, ETHERSCAN_API_KEY, HELIUS_API_KEY, ANKR_API_KEY) come from
the process environment first, then from vasp-fusion/.env (git-ignored). They are
sent as a header (TronGrid), a query param (Etherscan, Helius) or the last segment of
the URL (Ankr) and never stored, logged or printed; cache.request_key() strips them
before anything is written, and an Ankr key is never part of the url the cache sees.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV = ROOT / ".env"
USER_AGENT = "vasp-fusion/0.1 (SIH 2026 PS 26182)"


class Transport(Protocol):
    def get(self, url: str, params: dict, headers: dict) -> tuple[int, bytes]:
        """Return (HTTP status, raw body). HTTP errors are returned, not raised."""

    def rpc(self, url: str, params: dict, headers: dict,
            secret: str | None = None) -> tuple[int, bytes]:
        """A JSON-RPC call: POST `params["method"]` with `params["params"]` (JSON text)
        to `url`, or to `url/secret` when the provider keeps its key in the path."""


class UrllibTransport:
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def get(self, url: str, params: dict, headers: dict) -> tuple[int, bytes]:
        full = f"{url}?{urllib.parse.urlencode(params)}" if params else url
        req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT,
                                                    "Accept": "application/json", **headers})
        return self._send(req)

    def rpc(self, url: str, params: dict, headers: dict,
            secret: str | None = None) -> tuple[int, bytes]:
        body = {"jsonrpc": "2.0", "id": 1, "method": params["method"],
                "params": json.loads(params["params"])}
        req = urllib.request.Request(
            f"{url}/{secret}" if secret else url, data=json.dumps(body).encode(), method="POST",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                     "Content-Type": "application/json", **headers})
        return self._send(req)

    def _send(self, req: urllib.request.Request) -> tuple[int, bytes]:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read() or b""
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            return 599, str(getattr(e, "reason", e)).encode()  # treated as retryable


def load_env(path: Path | None = None) -> dict[str, str]:
    """KEY=VALUE lines from `path` (default vasp-fusion/.env), each overridden by the
    process env when set there."""
    path = path or DEFAULT_ENV
    vals: dict[str, str] = {}
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    for k in list(vals):
        if os.environ.get(k):
            vals[k] = os.environ[k]
    return vals


def api_key(name: str, env_path: Path | None = None) -> str | None:
    return os.environ.get(name) or load_env(env_path).get(name) or None
