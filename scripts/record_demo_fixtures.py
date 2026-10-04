"""Record the demo wallets' traces from the live APIs (run once, commit the JSON).

    python scripts/record_demo_fixtures.py            # every wallet in demo/cases.json
    python scripts/record_demo_fixtures.py tron-ofac  # one
    python scripts/record_demo_fixtures.py watch-tron-ofac-listed   # a watchlist wallet's
                                                      # first check (demo/watchlist.json)
    python scripts/record_demo_fixtures.py --extend   # keep what is recorded, fetch only
                                                      # the requests a code change added

For each wallet this runs the real `run_case` against the live chain APIs and the
real label DB, and writes:

* tests/fixtures/demo/<id>.json   every request the trace made (keyed by
  request_key(), API keys stripped) with the untouched response body;
* tests/fixtures/demo/labels.json the real label rows the traces touched, so the
  tests see exactly the labels the full DB would give them;
* tests/fixtures/demo/expected.json the headline result of each case, which the
  tests then have to reproduce offline.

Tests replay these through FixtureTransport and never reach the network.

Record with ETHERSCAN_API_KEY set: the tests replay the Etherscan backend (a key
selects it; without one the adapter talks to Blockscout, a different URL).
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from record_chain_fixtures import RecordingTransport, _secrets  # noqa: E402
from vaspfusion.cases import case_headline, run_case, trace_provider  # noqa: E402
from vaspfusion.chains.cache import ChainCache, Fetcher, request_key  # noqa: E402
from vaspfusion.labels.lookup import LabelStore  # noqa: E402
from vaspfusion.trace import TraceConfig  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "demo"
DEMO = ROOT / "demo" / "cases.json"
WATCH = ROOT / "demo" / "watchlist.json"


def watch_traces() -> list[dict]:
    """The watchlist wallets that need a trace of their own, as case specs with nothing
    expected of them: they are recorded so the first check replays offline."""
    return [{"address": w["address"], "chain": w["chain"], **w["trace"]}
            for w in json.loads(WATCH.read_text())["watch"] if w.get("trace")]


class ExtendingTransport(RecordingTransport):
    """Answers a request that is already in the fixture from the fixture, and fetches
    (and records) only the others. The recorded pages stay byte-for-byte what they were,
    so a code change that reads more pages does not also change the old ones."""

    def __init__(self, recorded: dict):
        super().__init__()
        self.recorded, self.fetched = recorded, 0

    def get(self, url, params, headers):
        key = request_key(url, params)
        if key not in self.recorded:
            self.fetched += 1
            return super().get(url, params, headers)
        self.responses[key] = self.recorded[key]
        body = self.recorded[key]["body"]
        return self.recorded[key]["status"], \
            (json.dumps(body) if not isinstance(body, str) else body).encode()


class RecordingLabels:
    """The real label store, remembering every row it returned."""

    def __init__(self, store: LabelStore, seen: dict):
        self.store, self.seen = store, seen

    def lookup_many(self, pairs):
        found = self.store.lookup_many(pairs)
        for (address, chain), label in found.items():
            self.seen[f"{chain}:{address}"] = {"query_chain": chain, **label.as_dict()}
        return found


def main(wanted: list[str]) -> None:
    extend = "--extend" in wanted
    wanted = [w for w in wanted if w != "--extend"]
    OUT.mkdir(parents=True, exist_ok=True)
    cases = json.loads(DEMO.read_text())["cases"] + watch_traces()
    labels_path, expected_path = OUT / "labels.json", OUT / "expected.json"
    seen = json.loads(labels_path.read_text())["labels"] if labels_path.exists() else {}
    expected = json.loads(expected_path.read_text()) if expected_path.exists() else {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with LabelStore() as store:
        for spec in cases:
            if wanted and spec["id"] not in wanted:
                continue
            path = OUT / f"{spec['id']}.json"
            rec = ExtendingTransport(json.loads(path.read_text())["responses"]) \
                if extend and path.exists() else RecordingTransport()
            with tempfile.TemporaryDirectory() as d:
                fetcher = Fetcher(ChainCache(Path(d) / "c.duckdb"), rec, offline=False)
                cfg = TraceConfig(max_hops=spec.get("max_hops", 3))
                case = run_case(spec["address"], spec["chain"],
                                trace_provider(spec["chain"], fetcher, cfg),
                                RecordingLabels(store, seen), case_id=spec["id"], cfg=cfg,
                                fetcher=fetcher, demo="expect" in spec)
            doc = {"_source": f"{spec['chain']} trace of {spec['address']}, max_hops="
                              f"{cfg.max_hops}, live APIs", "_recorded": today,
                   "responses": rec.responses}
            text = json.dumps(doc, indent=1, sort_keys=True) + "\n"
            for secret in _secrets():
                assert secret not in text, f"an API key leaked into fixture {spec['id']}"
            (OUT / f"{spec['id']}.json").write_text(text)
            got = (case["outcome"], case["top_vasp"])
            if "expect" not in spec:
                print(f"{spec['id']}: {len(rec.responses)} responses, {len(text) // 1024} KB, "
                      f"{got[0]} top={got[1]} (a watchlist wallet: nothing is expected of it)")
                continue
            expected[spec["id"]] = case_headline(case)
            want = (spec["expect"]["outcome"], spec["expect"]["top_vasp"])
            new = f" ({rec.fetched} new)" if extend and hasattr(rec, "fetched") else ""
            print(f"{spec['id']}: {len(rec.responses)} responses{new}, {len(text) // 1024} KB, "
                  f"{got[0]} top={got[1]}" + ("" if got == want else f"  !! expected {want}"))
    labels_path.write_text(json.dumps(
        {"_source": "rows of the label DB returned while tracing the demo wallets (real "
                    "labels; derived rows come from derived/*.csv)",
         "labels": dict(sorted(seen.items()))},
        indent=1, sort_keys=True) + "\n")
    expected_path.write_text(json.dumps(dict(sorted(expected.items())), indent=1) + "\n")
    print(f"labels.json: {len(seen)} label rows")


if __name__ == "__main__":
    main(sys.argv[1:])
