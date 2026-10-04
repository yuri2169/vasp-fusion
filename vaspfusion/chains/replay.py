"""A transport that answers from recorded responses and never opens a socket.

The demo wallets' traces were recorded once from the live chain APIs
(scripts/record_demo_fixtures.py -> tests/fixtures/demo/<id>.json). `demo-cache`
replays them through this transport into a fresh chain cache, so the offline image
gets exactly the pages the demo reads, built from tracked files alone.
"""
from __future__ import annotations

import json
from pathlib import Path

from .base import ProviderError
from .cache import request_key


class NotRecorded(ProviderError):
    """The trace asked for a page the recording does not hold."""


class RecordedTransport:
    def __init__(self, *fixture_files: Path | str):
        self.responses: dict[str, dict] = {}
        for path in fixture_files:
            self.responses.update(json.loads(Path(path).read_text())["responses"])
        self.calls = 0

    def get(self, url: str, params: dict, headers: dict) -> tuple[int, bytes]:
        key = request_key(url, params)
        if key not in self.responses:
            raise NotRecorded(f"request not in the recorded fixtures: {key}")
        self.calls += 1
        body = self.responses[key]["body"]
        return self.responses[key]["status"], \
            (json.dumps(body) if not isinstance(body, str) else body).encode()

    def rpc(self, url: str, params: dict, headers: dict,
            secret: str | None = None) -> tuple[int, bytes]:
        return self.get(url, params, headers)
