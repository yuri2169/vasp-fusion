"""Replay of recorded live responses (scripts/record_chain_fixtures.py). No network."""
import json
from pathlib import Path

from vaspfusion.chains.cache import ChainCache, Fetcher, request_key

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chains"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class FixtureTransport:
    def __init__(self, *names: str):
        self.responses = {}
        for n in names:
            self.responses.update(load_fixture(n)["responses"])
        self.calls = 0

    def get(self, url, params, headers):
        key = request_key(url, params)
        if key not in self.responses:
            raise AssertionError(f"request not in the recorded fixture (would go live): {key}")
        self.calls += 1
        r = self.responses[key]
        body = r["body"]
        return r["status"], (json.dumps(body) if not isinstance(body, str) else body).encode()
