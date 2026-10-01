"""The training set of the deposit-address model (B6): real addresses, one row each.

Positives: the addresses B4's rules derived as an exchange's deposit address.
Negatives:
  * customers - the wallets that paid into those deposit addresses, minus anything
    that carries a label or that the rules fired on. A deposit address only ever
    pays its exchange's own wallet, so a sender into one is not a deposit address;
  * the chain's labelled wallets that are not deposit addresses (exchange wallets,
    sanctioned addresses, ...) and the gas stations the discovery runs reported.

Every address, of either class, is read with its discovery run's own protocol: the
same listings, the same `since`, the same row limit, and nothing later than the
run's last positive transfer. How an address was fetched therefore says nothing
about its class. An address under test is judged without its own label.

`group` is what leave-one-exchange-out holds out together: an exchange's deposit
addresses, their customers and the exchange's own wallets ("other" for a labelled
wallet that is no exchange's).
"""
from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from ..chains.base import ProviderError
from ..discover.crawl import Finding, _stable_rows, _warm
from ..discover.rules import DiscoverConfig, is_seed
from ..discover.store import read_findings
from .features import FEATURES, LABEL_FEATURES, address_features

SEED = 26182
META = ["address", "chain", "y", "group", "source", "run", "first_ts", "n_rows", "complete",
        "label_entity"]
COLUMNS = META + FEATURES + LABEL_FEATURES
_COUNTS = {"n_senders", "n_recipients", "n_in", "n_out", "gas_payers"}


@dataclass(frozen=True)
class Run:
    """One discovery run and the fetch protocol its candidates were read with."""
    name: str
    chain: str
    since: datetime
    limit: int
    findings: tuple[Finding, ...]
    stations: tuple[dict, ...] = ()


@dataclass(frozen=True)
class DatasetConfig:
    per_exchange: int = 700          # customers sampled per exchange
    seed: int = SEED
    rules: DiscoverConfig = DiscoverConfig()


def load_runs(derived_dir: Path | str) -> list[Run]:
    """Every discovery run in the folder (`<name>.csv` + `<name>_report.json`), by name."""
    runs = []
    for path in sorted(Path(derived_dir).glob("*.csv")):
        report_path = path.with_name(f"{path.stem}_report.json")
        if not report_path.exists():
            continue
        report = json.loads(report_path.read_text())
        cfg = report["config"]
        start = datetime.strptime(cfg["window_start"], "%Y-%m-%dT%H:%M:%SZ") \
            .replace(tzinfo=timezone.utc)
        runs.append(Run(name=path.stem, chain=report["chain"],
                        since=start - timedelta(days=cfg["lookback_days"]),
                        limit=cfg["candidate_limit"], findings=tuple(read_findings(path)),
                        stations=tuple(report.get("stations", ()))))
    return runs


def _read(provider, address: str, run: Run):
    rows, complete = _stable_rows(provider, address, "both", run.since, run.limit)
    return rows, complete, provider.gas_events(address, since=run.since)


def _example(address: str, run: Run, read, labels, cutoff, cfg: DatasetConfig) -> dict | None:
    rows, complete, events = read
    if cutoff is not None:
        rows = [t for t in rows if t.block_time <= cutoff]
        events = [e for e in events if e.time <= cutoff]
    near = {a for t in rows for a in (t.from_addr, t.to_addr, t.fee_payer) if a}
    near |= {e.payer for e in events}
    near.discard(address)                        # judged without its own label
    lab = {a: l for (a, _), l in labels.lookup_many({(a, run.chain) for a in near}).items()}
    f = address_features(address, rows, events, lab, cfg=cfg.rules)
    if f is None:
        return None
    return {"address": address, "chain": run.chain, "run": run.name, "complete": int(complete),
            **f}


def build(runs: list[Run], provider, extra_provider, labels,
          cfg: DatasetConfig = DatasetConfig(), progress=None,
          workers: int = 1) -> tuple[list[dict], dict]:
    """`provider` reads the positives (the discovery crawl's cache holds them);
    `extra_provider` reads the negatives. Both must page the same way."""
    chain = runs[0].chain
    fired = {f.address for run in runs for f in run.findings}
    stats = {"positives": 0, "customers_seen": 0, "customers_in_two_exchanges": 0,
             "customers": {}, "labelled": 0, "stations": 0, "errors": 0, "empty": 0}

    todo: list[tuple[str, Run, int, str, str, object]] = []   # address, run, y, group, source
    taken: set[str] = set()

    def add(address, run, y, group, source, prov) -> None:
        if address not in taken:
            taken.add(address)
            todo.append((address, run, y, group, source, prov))

    for run in runs:                              # an address in two runs: the first one
        for f in sorted(run.findings, key=lambda f: f.address):
            if f.status == "derived":
                add(f.address, run, 1, f.entity, "derived", provider)
    positives = list(todo)

    reads: dict[str, tuple] = {}

    def fetch(item) -> None:
        address, run, *_, prov = item
        reads[address] = _read(prov, address, run)

    def read_all(items, stage: str) -> None:
        _warm(workers, items, lambda it: _read(it[-1], it[0], it[1]), stage, progress)
        for i, item in enumerate(items):
            if progress:
                progress(f"{stage} (features)", i + 1, len(items))
            try:
                fetch(item)
            except ProviderError:
                stats["errors"] += 1

    read_all(positives, "positives")
    cutoff: dict[str, datetime] = {}
    paid_into: dict[str, set[str]] = {}
    first_run: dict[str, Run] = {}
    for address, run, _, group, _, _ in positives:
        if address not in reads:
            continue
        rows = reads[address][0]
        if rows:
            last = max(t.block_time for t in rows)
            cutoff[run.name] = max(cutoff.get(run.name, last), last)
        for t in rows:
            if t.to_addr == address and t.from_addr != address \
                    and t.amount_usd is not None and t.amount_usd >= cfg.rules.dust:
                paid_into.setdefault(t.from_addr, set()).add(group)
                first_run.setdefault(t.from_addr, run)

    known = labels.lookup_many({(a, chain) for a in paid_into})
    ordinary = sorted(a for a in paid_into if a not in fired and (a, chain) not in known)
    stats["customers_seen"] = len(ordinary)
    stats["customers_in_two_exchanges"] = sum(1 for a in ordinary if len(paid_into[a]) > 1)
    by_exchange: dict[str, list[str]] = {}
    for a in ordinary:
        by_exchange.setdefault(min(paid_into[a]), []).append(a)
    for exchange in sorted(by_exchange):
        pool = by_exchange[exchange]
        rng = random.Random(f"{cfg.seed}:{exchange}")
        picked = sorted(rng.sample(pool, min(cfg.per_exchange, len(pool))))
        stats["customers"][exchange] = len(picked)
        for a in picked:
            add(a, first_run[a], 0, exchange, "customer", extra_provider)

    main = runs[0]
    before = len(todo)
    for lab in labels.non_deposit(chain):
        add(lab.address, main, 0, lab.entity if is_seed(lab) else "other",
            f"labelled:{lab.category}", extra_provider)
    stats["labelled"] = len(todo) - before
    before = len(todo)
    for run in runs:
        for s in run.stations:
            add(s["address"], run, 0, s["entity"], "gas_station", extra_provider)
    stats["stations"] = len(todo) - before
    stats["positives"] = len(positives)
    read_all(todo[len(positives):], "negatives")

    examples = []
    for address, run, y, group, source, _ in todo:
        if address not in reads:
            continue
        ex = _example(address, run, reads[address], labels, cutoff.get(run.name), cfg)
        if ex is None:
            stats["empty"] += 1
            continue
        examples.append({**ex, "y": y, "group": group, "source": source})
    examples.sort(key=lambda e: (e["chain"], e["address"]))
    by_source: dict[str, int] = {}
    for e in examples:
        by_source[e["source"]] = by_source.get(e["source"], 0) + 1
    stats["examples"] = len(examples)
    stats["by_source"] = dict(sorted(by_source.items()))
    stats["cutoff"] = {k: _iso(v) for k, v in sorted(cutoff.items())}
    return examples, stats


# ------------------------------------------------------------------ the CSV
def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cell(name: str, value) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    if name == "first_ts":
        return _iso(value)
    if name in FEATURES or name in LABEL_FEATURES:
        return str(int(value)) if name in _COUNTS else repr(round(float(value), 6))
    return str(value)


def write_dataset(path: Path | str, examples: list[dict]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(COLUMNS)
        for e in sorted(examples, key=lambda e: (e["chain"], e["address"])):
            w.writerow([_cell(c, e.get(c)) for c in COLUMNS])
    return path


def read_dataset(path: Path | str) -> pl.DataFrame:
    schema = {c: pl.String for c in META}
    schema.update({"y": pl.Int8, "n_rows": pl.Int32, "complete": pl.Int8})
    schema.update({c: pl.Float64 for c in FEATURES + LABEL_FEATURES})
    df = pl.read_csv(path, schema_overrides=schema, null_values=[""])
    return df.with_columns(
        pl.col("first_ts").str.strptime(pl.Datetime("us", "UTC"), "%Y-%m-%dT%H:%M:%SZ"))
