"""Replay of the recorded discovery responses (scripts/record_discover_fixtures.py).
Everything in tests/fixtures/discover is real chain data and real label rows."""
import json
from pathlib import Path

from vaspfusion.chains.cache import ChainCache, Fetcher, request_key
from vaspfusion.labels.lookup import Label

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIX = FIXTURES / "discover"


def load(name: str) -> dict:
    """A discovery fixture, or one of the chain adapters' (tests/fixtures/chains)."""
    path = FIX / f"{name}.json"
    return json.loads((path if path.exists() else FIXTURES / "chains" / f"{name}.json").read_text())


class ReplayTransport:
    """Answers only the requests recorded in the given fixtures."""

    def __init__(self, *names: str):
        self.responses = {}
        for n in names:
            self.responses.update(load(n)["responses"])
        self.calls = 0

    def get(self, url, params, headers):
        key = request_key(url, params)
        if key not in self.responses:
            raise AssertionError(f"request not in the recorded fixture (would go live): {key}")
        self.calls += 1
        body = self.responses[key]["body"]
        return self.responses[key]["status"], \
            (json.dumps(body) if not isinstance(body, str) else body).encode()


def replay_fetcher(tmp_path, *names: str, offline: bool = False) -> Fetcher:
    return Fetcher(ChainCache(tmp_path / "cache.duckdb"), ReplayTransport(*names),
                   offline=offline, sleep=lambda s: None)


class FixtureLabels:
    """The label rows the full label DB returned while a fixture was recorded."""

    def __init__(self, name: str):
        self.rows = {key: Label(**{k: v for k, v in row.items() if k != "query_chain"})
                     for key, row in load(name)["labels"].items()}

    def lookup_many(self, pairs):
        return {(a, c): self.rows[f"{c}:{a}"] for a, c in pairs if f"{c}:{a}" in self.rows}

    def lookup(self, address, chain):
        return self.rows.get(f"{chain}:{address}")
