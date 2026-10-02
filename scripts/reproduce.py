"""`make reproduce`: regenerate every artifact that comes from tracked files, and check
that nothing changed. No network.

    python scripts/reproduce.py                 # everything below
    python scripts/reproduce.py --skip model,tests
    python scripts/reproduce.py --full          # also replay the crawls from local caches

What is regenerated, and from what:

  labels        data/labels.duckdb          research label CSVs + derived/ + model scores
  model         artifacts/model_v1/<chain>/  the tracked dataset.csv (train, calibrate, measure)
  abstain       artifacts/abstain_v1/tron/   the tracked claims.csv
  demo-cache    a chain cache                tests/fixtures/demo (recorded chain responses)
  demo          the seven demo cases         that cache, OFFLINE=1; golden fingerprints
  verify        each case traced again       cache only
  golden        tests/golden/, expected.json the recorded fixtures
  mocks         mocks/                       the label DB (seeded)
  openapi       docs/openapi.json            the schemas
  tests         the test suite

  --full adds   derived/*.csv, dataset.csv, claims.csv, replayed with OFFLINE=1 from the
                crawl caches in data/ (discover, model, abstain); skipped where a cache
                is not on this machine.

Then every tracked artifact is compared with what git holds. One field is allowed to
differ: `trained_at` in a model's metrics.json (the time of this run); such a file is
put back as it was. Anything else that changed is listed and the run fails.

The demo cases and the cache are written to data/reproduce/, not to the working stores.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ("artifacts", "derived", "mocks", "docs/openapi.json", "tests/golden",
             "tests/fixtures/demo/expected.json")
VOLATILE = ("trained_at",)                 # the only fields allowed to differ between runs
SCRATCH = ROOT / "data" / "reproduce"


# ------------------------------------------------------------------ comparing
def _without(obj, keys):
    if isinstance(obj, dict):
        return {k: _without(v, keys) for k, v in obj.items() if k not in keys}
    if isinstance(obj, list):
        return [_without(v, keys) for v in obj]
    return obj


def classify(path: str, before: bytes | None, after: bytes | None) -> str:
    """How a tracked file changed: `same`, `only_timestamp` (a JSON file that differs in
    nothing but its volatile fields), or `changed` (also: deleted, or newly created)."""
    if before == after:
        return "same"
    if before is None or after is None:
        return "changed"
    if path.endswith(".json"):
        try:
            if _without(json.loads(before), VOLATILE) == _without(json.loads(after), VOLATILE):
                return "only_timestamp"
        except ValueError:
            pass
    return "changed"


def git(*args: str, binary: bool = False):
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout
    return out if binary else out.decode()


def tracked_changes() -> tuple[list[str], list[str], list[str]]:
    """(changed, only the timestamp changed, new untracked files) among the artifacts."""
    changed, stamped, new = [], [], []
    for line in git("status", "--porcelain", "--untracked-files=all", "--", *ARTIFACTS).splitlines():
        status, path = line[:2], line[3:].strip().strip('"')
        if status == "??":
            new.append(path)
            continue
        before = git("show", f"HEAD:{path}", binary=True) if "A" not in status else None
        file = ROOT / path
        kind = classify(path, before, file.read_bytes() if file.exists() else None)
        (stamped if kind == "only_timestamp" else changed).append(path)
    return changed, stamped, new


# ------------------------------------------------------------------ running
def research_dir() -> Path | None:
    for parent in ROOT.parents:                 # a worktree sits deeper than the checkout
        if (parent / "research" / "data").is_dir():
            return parent / "research" / "data"
    return None


class Run:
    def __init__(self, skip: set[str]):
        self.skip, self.rows, self.failed = skip, [], False
        self.env = {**os.environ, "OFFLINE": "1", "ETHERSCAN_API_KEY":
                    os.environ.get("ETHERSCAN_API_KEY") or "offline-replay",
                    "PYTHONWARNINGS": "ignore"}

    def step(self, name: str, what: str, *cmd: str, env: dict | None = None,
             needs: Path | None = None) -> bool:
        if name in self.skip:
            self.rows.append((name, "skipped", "--skip", what))
            return True
        if needs is not None and not needs.exists():
            self.rows.append((name, "skipped", f"{needs.relative_to(ROOT)} is not here", what))
            return True
        started = time.monotonic()
        print(f"\n== {name}: {what}", flush=True)
        done = subprocess.run([sys.executable, *cmd], cwd=ROOT, env={**self.env, **(env or {})})
        took = f"{time.monotonic() - started:.0f} s"
        good = done.returncode == 0
        self.failed |= not good
        self.rows.append((name, "ok" if good else "FAILED", took, what))
        return good

    def report(self) -> None:
        print("\n" + "=" * 78)
        for name, state, note, what in self.rows:
            print(f"  {name:<12}{state:<9}{note:<28}{what}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--skip", default="", help="comma-separated step names to skip")
    p.add_argument("--full", action="store_true",
                   help="also replay discovery, the model's dataset and the abstain traces "
                        "from the local crawl caches (OFFLINE=1)")
    args = p.parse_args()
    run = Run({s for s in args.skip.split(",") if s})
    cli = ("-m", "vaspfusion.cli")
    SCRATCH.mkdir(parents=True, exist_ok=True)
    cache, cases = SCRATCH / "chain_cache.duckdb", SCRATCH / "case.duckdb"
    cases.unlink(missing_ok=True)
    demo_env = {"VASPFUSION_CHAIN_CACHE": str(cache), "VASPFUSION_CASE_DB": str(cases)}
    dirty_before, _, new_before = tracked_changes()
    if dirty_before:
        print("These artifacts already differ from git before anything ran; commit or "
              "restore them first:\n  " + "\n  ".join(dirty_before))
        raise SystemExit(1)

    research = research_dir()
    if research is None:
        run.rows.append(("labels", "FAILED", "research/data not found",
                         "the label CSVs are outside this repository"))
        run.failed = True
    if args.full:
        data = ROOT / "data"
        for since, name, entities in ((None, None, None),
                                      ("2026-08-01", "tron_coindcx_aug", "CoinDCX"),
                                      ("2025-05-25", "tron_coindcx_2025", "CoinDCX")):
            extra = [x for pair in (("--entities", entities), ("--since", since),
                                    ("--name", name)) if pair[1] for x in pair]
            run.step(f"discover{'' if name is None else ':' + name[5:]}",
                     "derived deposit addresses, replayed from the crawl cache",
                     *cli, "discover", "--chain", "tron", *extra,
                     needs=data / "discover_cache.duckdb")
        for chain in ("tron", "ethereum"):
            run.step(f"data:{chain}", "the model's training set, replayed",
                     *cli, "model-data", "--chain", chain, needs=data / "model_cache.duckdb")
    for chain in ("tron", "ethereum"):
        run.step("model", f"train, calibrate and measure the {chain} model from dataset.csv",
                 *cli, "model", "--chain", chain)
    if research is not None:
        run.step("labels", "the label database, from the label CSVs + derived/ + scores",
                 *cli, "labels", "--research", str(research), "--db", "data/labels.duckdb")
    if args.full:
        run.step("abstain:full", "the abstain traces, replayed from the cache",
                 *cli, "abstain-eval", needs=ROOT / "data" / "abstain_cache.duckdb")
    run.step("abstain", "the abstain bar, re-measured from the tracked claims",
             *cli, "abstain-eval", "--from-claims")
    if run.step("demo-cache", "the demo's chain cache, from the recorded fixtures",
                *cli, "demo-cache", "--out", str(cache)):
        run.step("demo", "the seven demo cases, offline, against the golden fingerprints",
                 *cli, "demo", "--golden", "tests/golden/fingerprints.json", env=demo_env)
        run.step("verify", "each case traced again from the cache only",
                 *cli, "verify", "--all", env=demo_env)
    run.step("golden", "the golden case files and fingerprints", "tests/refresh_golden.py")
    run.step("golden", "the demo figures (expected.json)", "tests/refresh_expected.py")
    run.step("mocks", "the mock files", "scripts/make_mocks.py")
    run.step("openapi", "the OpenAPI schema", *cli, "openapi", "--out", "docs/openapi.json")
    run.step("tests", "the test suite", "-m", "pytest", "-q", "-p", "no:cacheprovider")

    changed, stamped, new = tracked_changes()
    for path in stamped:                       # only `trained_at` moved: put the file back
        git("checkout", "--", path)
    created = [n for n in new if n not in new_before]
    for path in created:                       # written by a step, not tracked: remove again
        (ROOT / path).unlink()
    run.report()
    print(f"\n  tracked artifacts compared with git: {', '.join(ARTIFACTS)}")
    if stamped:
        print(f"  only the run's timestamp differed (restored): {', '.join(stamped)}")
    if created:
        print(f"  written but not tracked (removed again): {', '.join(created)}")
    if changed:
        print("  CHANGED (read the diff with `git diff`):\n    " + "\n    ".join(changed))
    if changed or run.failed:
        print("\nREPRODUCE: FAILED")
        raise SystemExit(1)
    print("\nREPRODUCE: GREEN. Every artifact regenerated to what git holds.")


if __name__ == "__main__":
    main()
