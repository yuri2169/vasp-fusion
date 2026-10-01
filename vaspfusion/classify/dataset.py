"""The training set of the deposit-address model (B6): real addresses, one row each.

Positives: the addresses B4's rules derived as an exchange's deposit address.
Negatives:
  * customers - the wallets that paid into those deposit addresses, minus anything
    that carries a label or that the rules fired on. A deposit address only ever
    pays its exchange's own wallet, so a sender into one is not a deposit address;
  * the chain's labelled wallets that are not deposit addresses (exchange wallets,
    sanctioned addresses, ...) and the gas stations the discovery runs reported.

Every address, of either class, is read with its discovery run's own protocol: the
same listings, the same `since`, the same row limit, nothing later than the run's
last positive transfer, and only the first `horizon_days` from its first transfer.
How an address was fetched therefore says nothing about its class or its run. An
address under test is judged without its own label.

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
from ..discover.evaluate import EvalConfig, sample
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


    def read(self, provider, address: str):
        """(stablecoin transfers, whether that is all of them, gas events)."""
        rows, complete = _stable_rows(provider, address, "both", self.since, self.limit)
        return rows, complete, provider.gas_events(address, since=self.since)


@dataclass(frozen=True)
class Listing:
    """The fetch protocol of the explorer-tagged dataset: an address's earliest `limit`
    transfers of every asset (what B4's hold-out test read)."""
    name: str
    chain: str
    limit: int

    def read(self, provider, address: str):
        rows = provider.transfers(address, "both", limit=self.limit)
        complete = getattr(rows, "complete", len(rows) < self.limit)
        return rows, complete, provider.gas_events(address, limit=self.limit)


@dataclass(frozen=True)
class DatasetConfig:
    per_exchange: int = 700          # customers sampled per exchange
    seed: int = SEED
    # Only an address's first `horizon_days` of transfers are read. The discovery runs
    # looked back over different spans (two weeks, two months, sixteen months); without
    # one horizon, how long a listing runs would tell which run an address came from.
    horizon_days: float | None = 14.0
    rules: DiscoverConfig = DiscoverConfig()


@dataclass(frozen=True)
class TaggedConfig:
    chain: str = "ethereum"
    # "Bilaxy" is the upstream slug of 5,000 addresses Etherscan tags "Binance Dep"
    entities: tuple[str, ...] = ("Bitget", "Bilaxy")
    n_positive: int = 300            # tagged deposit addresses per exchange
    n_negative: int = 300            # tagged non-deposit addresses (B4's hold-out sample)
    per_exchange: int = 300          # customers sampled per exchange
    limit: int = 200                 # transfers read per address
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


def _read(provider, address: str, run):
    return run.read(provider, address)


def _example(address: str, run, read, labels, cutoff, rules: DiscoverConfig,
             horizon: timedelta | None = None) -> dict | None:
    rows, complete, events = read
    if cutoff is not None:
        rows = [t for t in rows if t.block_time <= cutoff]
        events = [e for e in events if e.time <= cutoff]
    if horizon is not None and rows:
        end = min(t.block_time for t in rows) + horizon
        rows = [t for t in rows if t.block_time <= end]
        events = [e for e in events if e.time <= end]
    near = {a for t in rows for a in (t.from_addr, t.to_addr, t.fee_payer) if a}
    near |= {e.payer for e in events}
    near.discard(address)                        # judged without its own label
    lab = {a: l for (a, _), l in labels.lookup_many({(a, run.chain) for a in near}).items()}
    f = address_features(address, rows, events, lab, cfg=rules)
    if f is None:
        return None
    return {"address": address, "chain": run.chain, "run": run.name, "complete": int(complete),
            **f}


def _pays(t, address: str, dust) -> bool:
    """Is this transfer a real payment into `address`? Unknown tokens are spam senders."""
    if t.to_addr != address or t.from_addr == address or "@" in t.asset:
        return False
    return t.amount_usd >= dust if t.amount_usd is not None else t.amount > 0


def _assemble(chain: str, positives: list[tuple], known_negatives: list[tuple], not_ordinary,
              provider, extra_provider, labels, per_exchange: int, seed: int,
              rules: DiscoverConfig, progress, workers: int,
              horizon: timedelta | None = None) -> tuple[list[dict], dict]:
    """positives / known_negatives: (address, listing, group, source). Customers are found
    in the positives' own listings. `not_ordinary`: addresses that may not be customers."""
    stats = {"positives": 0, "customers_seen": 0, "customers_in_two_exchanges": 0,
             "customers": {}, "labelled": 0, "errors": 0, "empty": 0}
    todo: list[tuple] = []                        # address, listing, y, group, source, provider
    taken: set[str] = set()

    def add(address, run, y, group, source, prov) -> None:
        if address not in taken:
            taken.add(address)
            todo.append((address, run, y, group, source, prov))

    for address, run, group, source in positives:
        add(address, run, 1, group, source, provider)
    n_positive = len(todo)
    reads: dict[str, tuple] = {}

    def read_all(items, stage: str) -> None:
        _warm(workers, items, lambda it: _read(it[-1], it[0], it[1]), stage, progress)
        for i, (address, run, *_, prov) in enumerate(items):
            if progress:
                progress(f"{stage} (features)", i + 1, len(items))
            try:
                reads[address] = _read(prov, address, run)
            except ProviderError:
                stats["errors"] += 1

    read_all(todo, "positives")
    cutoff: dict[str, datetime] = {}
    paid_into: dict[str, set[str]] = {}
    first_run: dict[str, object] = {}
    for address, run, _, group, _, _ in todo:
        if address not in reads:
            continue
        rows = reads[address][0]
        if rows:
            last = max(t.block_time for t in rows)
            cutoff[run.name] = max(cutoff.get(run.name, last), last)
        for t in rows:
            if _pays(t, address, rules.dust):
                paid_into.setdefault(t.from_addr, set()).add(group)
                first_run.setdefault(t.from_addr, run)

    known = labels.lookup_many({(a, chain) for a in paid_into})
    ordinary = sorted(a for a in paid_into
                      if a not in not_ordinary and a not in taken and (a, chain) not in known)
    stats["customers_seen"] = len(ordinary)
    stats["customers_in_two_exchanges"] = sum(1 for a in ordinary if len(paid_into[a]) > 1)
    by_exchange: dict[str, list[str]] = {}
    for a in ordinary:
        by_exchange.setdefault(min(paid_into[a]), []).append(a)
    for exchange in sorted(by_exchange):
        pool = by_exchange[exchange]
        rng = random.Random(f"{seed}:{exchange}")
        picked = sorted(rng.sample(pool, min(per_exchange, len(pool))))
        stats["customers"][exchange] = len(picked)
        for a in picked:
            add(a, first_run[a], 0, exchange, "customer", extra_provider)

    before = len(todo)
    for address, run, group, source in known_negatives:
        add(address, run, 0, group, source, extra_provider)
    stats["labelled"] = len(todo) - before
    stats["positives"] = n_positive
    read_all(todo[n_positive:], "negatives")

    examples = []
    for address, run, y, group, source, _ in todo:
        if address not in reads:
            continue
        ex = _example(address, run, reads[address], labels, cutoff.get(run.name), rules,
                      horizon)
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


def build(runs: list[Run], provider, extra_provider, labels,
          cfg: DatasetConfig = DatasetConfig(), progress=None,
          workers: int = 1) -> tuple[list[dict], dict]:
    """The dataset of a chain with discovery runs (Tron). `provider` reads the positives
    (the discovery crawl's cache holds them); `extra_provider` reads the negatives. Both
    must page the same way."""
    chain = runs[0].chain
    fired = {f.address for run in runs for f in run.findings}
    seen: set[str] = set()
    positives = []
    for run in runs:                              # an address in two runs: the first one
        for f in sorted(run.findings, key=lambda f: f.address):
            if f.status == "derived" and f.address not in seen:
                seen.add(f.address)
                positives.append((f.address, run, f.entity, "derived"))
    main = runs[0]
    known = [(lab.address, main, lab.entity if is_seed(lab) else "other",
              f"labelled:{lab.category}") for lab in labels.non_deposit(chain)]
    known += [(s["address"], run, s["entity"], "gas_station")
              for run in runs for s in run.stations]
    horizon = None if cfg.horizon_days is None else timedelta(days=cfg.horizon_days)
    return _assemble(chain, positives, known, fired, provider, extra_provider, labels,
                     cfg.per_exchange, cfg.seed, cfg.rules, progress, workers, horizon)


def build_tagged(provider, labels, cfg: TaggedConfig = TaggedConfig(), progress=None,
                 workers: int = 1) -> tuple[list[dict], dict]:
    """The dataset of a chain whose truth is an explorer's tags (Ethereum): the rules
    never saw these labels. Positives: a seeded sample of each exchange's tagged deposit
    addresses. Negatives: B4's hold-out sample of tagged addresses that are not deposit
    addresses (half exchange wallets, half anything else), and the positives' customers."""
    listing = Listing(f"tagged_{cfg.chain}", cfg.chain, cfg.limit)
    positives, known = [], []
    for i, entity in enumerate(cfg.entities):
        pos, neg_exchange, neg_other = sample(labels, EvalConfig(
            chain=cfg.chain, entity=entity, n_positive=cfg.n_positive,
            n_negative=cfg.n_negative, seed=cfg.seed, limit=cfg.limit))
        positives += [(a, listing, entity, "explorer_tag") for a in pos]
        if i == 0:                                # one negative sample: the first exchange's
            tags = labels.lookup_many({(a, cfg.chain) for a in neg_exchange + neg_other})
            for a in neg_exchange + neg_other:
                lab = tags[(a, cfg.chain)]
                known.append((a, listing, lab.entity if is_seed(lab) else "other",
                              f"labelled:{lab.category}"))
    return _assemble(cfg.chain, positives, known, set(), provider, provider, labels,
                     cfg.per_exchange, cfg.seed, cfg.rules, progress, workers)


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
