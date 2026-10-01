"""Replay of the demo wallets' recorded traces (scripts/record_demo_fixtures.py).

Everything here is real: the wallets in demo/cases.json, the API responses in
tests/fixtures/demo/<id>.json and the label rows in labels.json. No network.
"""
import json
from pathlib import Path

from vaspfusion.cases import run_case, trace_provider
from vaspfusion.chains.cache import ChainCache, Fetcher, request_key
from vaspfusion.labels.lookup import Label
from vaspfusion.trace import TraceConfig

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "demo"
SPECS = {c["id"]: c for c in json.loads((ROOT / "demo" / "cases.json").read_text())["cases"]}


class DemoTransport:
    """Answers only the requests recorded for the given demo wallets."""

    def __init__(self, *case_ids: str):
        self.responses = {}
        for cid in case_ids:
            self.responses.update(json.loads((FIX / f"{cid}.json").read_text())["responses"])
        self.calls = 0

    def get(self, url, params, headers):
        key = request_key(url, params)
        if key not in self.responses:
            raise AssertionError(f"request not in the recorded fixture (would go live): {key}")
        self.calls += 1
        body = self.responses[key]["body"]
        return self.responses[key]["status"], \
            (json.dumps(body) if not isinstance(body, str) else body).encode()


class DemoLabels:
    """The label rows the full label DB returned while the fixtures were recorded."""

    def __init__(self):
        rows = json.loads((FIX / "labels.json").read_text())["labels"]
        self.rows = {key: Label(**{k: v for k, v in row.items() if k != "query_chain"})
                     for key, row in rows.items()}

    def lookup_many(self, pairs):
        return {(a, c): self.rows[f"{c}:{a}"] for a, c in pairs if f"{c}:{a}" in self.rows}


def demo_fetcher(cache_path, *case_ids: str, offline: bool = False) -> Fetcher:
    transport = None if offline else DemoTransport(*(case_ids or SPECS))
    return Fetcher(ChainCache(cache_path), transport, offline=offline, sleep=lambda s: None)


def demo_provider(chain: str, fetcher: Fetcher, cfg: TraceConfig = TraceConfig()):
    # any non-empty key selects the Etherscan backend the fixtures were recorded from
    return trace_provider(chain, fetcher, cfg, key="test-key")


def run_demo(case_id: str, cache_path, offline: bool = False, **kw) -> dict:
    spec = SPECS[case_id]
    fetcher = demo_fetcher(cache_path, case_id, offline=offline)
    cfg = TraceConfig(max_hops=spec["max_hops"])
    return run_case(spec["address"], spec["chain"], demo_provider(spec["chain"], fetcher, cfg),
                    DemoLabels(), case_id=case_id, cfg=cfg, fetcher=fetcher, demo=True, **kw)
