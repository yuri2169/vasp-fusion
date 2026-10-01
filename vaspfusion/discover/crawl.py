"""The discovery crawl: an exchange's labelled wallets -> who paid into them -> the rules.

1. Seeds are the chain's labelled exchange wallets (rules.is_seed).
2. Each seed's inbound stablecoin transfers since `window_start` name its senders.
   A sender that is not itself a seed is a candidate deposit address.
3. Each candidate's own stablecoin history (from `lookback_days` before the window)
   goes through the sweep rule; only when it fires is the gas listing fetched and
   the gas rule applied.
4. An unlabelled payer that serves many fired addresses, nearly all of one
   exchange, is that exchange's gas station; the addresses it paid for move from
   "unlabelled" to "station". Stations are reported, not turned into labels: an
   energy-rental service would look the same from here.

Every request goes through the cache, candidates are processed in sorted order and
findings are sorted, so `OFFLINE=1` replays to the same result. With `workers` > 1
the listings are first fetched by a thread pool, which only warms the cache; the
rules then run in one thread over cached pages, so the result is the same.
"""
from __future__ import annotations

import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Callable

from ..chains.base import ProviderError, Transfer, sort_transfers
from .rules import (DiscoverConfig, Gas, Sweep, decide, evidence_text, gas_rule, is_seed,
                    sweep_rule)

WINDOW_START = datetime(2026, 9, 24, tzinfo=timezone.utc)


@dataclass(frozen=True)
class CrawlConfig:
    window_start: datetime = WINDOW_START
    lookback_days: int = 7              # candidate history starts this long before the window
    seed_limit: int = 1000              # inbound transfers read per seed wallet
    candidate_limit: int = 50           # transfers read per candidate
    max_candidates: int | None = None   # per seed, in order of first appearance
    entities: tuple[str, ...] | None = None   # only these exchanges
    rules: DiscoverConfig = DiscoverConfig()

    def window_text(self) -> str:
        return self.window_start.strftime("%Y-%m-%d %H:%M UTC")

    def as_dict(self) -> dict:
        d = asdict(self)
        d["window_start"] = self.window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        d["rules"]["dust"] = str(self.rules.dust)
        return d


@dataclass(frozen=True)
class Finding:
    """One address the sweep rule fired on: a derived label, a conflict, or one that
    was already labelled for that exchange."""
    address: str
    chain: str
    entity: str
    category: str
    kind: str
    status: str                 # derived | conflict | known
    rule: str                   # sweep | sweep+gas | sweep+station
    confidence: float | None
    evidence: str
    conflict: str | None
    sweep_target: str
    target_tier: str
    asset: str
    share: float
    received: str
    forwarded: str
    n_deposits: int
    n_senders: int
    n_sweeps: int
    median_delay_s: float | None
    gas_verdict: str
    gas_payer: str | None
    gas_payer_entity: str | None
    gas_kinds: str
    n_paid: int
    first_sweep_tx: str
    last_sweep_time: str
    complete: bool              # False: a listing was cut short (said in the evidence)


@dataclass
class DiscoveryResult:
    chain: str
    config: dict
    findings: list[Finding] = field(default_factory=list)
    stations: list[dict] = field(default_factory=list)
    stats: dict[str, dict] = field(default_factory=dict)      # per exchange
    totals: dict = field(default_factory=dict)


def _new_stats() -> dict:
    return {"seeds": 0, "active_seeds": 0, "inbound_rows": 0, "labelled_senders": 0,
            "candidates": 0, "fired": 0, "derived": 0, "conflict": 0, "known": 0,
            "errors": 0, "seed_errors": 0, "by_rule": {}, "by_gas": {}, "rejected": {},
            "median_sweep_delay_s": None}


def _stable_rows(provider, address: str, direction: str, since, limit: int):
    """The address's stablecoin transfers, and whether that is all of them."""
    rows, complete = [], True
    for asset in provider.traceable_assets[:-1]:        # the native coin is last
        got = provider.transfers(address, direction, since=since, limit=limit, asset=asset)
        rows += got
        complete = complete and getattr(got, "complete", len(got) < limit)
    return sort_transfers(rows), complete


def _most(payers: list[str], gas: Gas) -> str:
    return min(payers, key=lambda p: (-gas.payers[p], p))


def _stations(fired: dict[str, tuple[Sweep, Gas, object, bool]], chain: str,
              rules: DiscoverConfig) -> dict[str, dict]:
    """Payers without any label, judged on every fired address they paid for (whatever
    that address's own verdict): at least `min_station` of them, `station_share` of
    them one exchange's."""
    served: dict[str, Counter] = defaultdict(Counter)
    kinds: dict[str, set[str]] = defaultdict(set)
    labelled: set[str] = set()
    for sweep, gas, _, _ in fired.values():
        labelled |= set(gas.seed_payers) | set(gas.other_labels)
        for payer in gas.payers:
            served[payer][sweep.entity] += 1
            kinds[payer] |= set(gas.kinds_by_payer[payer])
    out = {}
    for payer, per in sorted(served.items()):
        if payer in labelled:
            continue
        total = sum(per.values())
        entity = min(per, key=lambda e: (-per[e], e))
        if total >= rules.min_station and per[entity] / total >= rules.station_share:
            out[payer] = {"address": payer, "chain": chain, "entity": entity,
                          "addresses": total, "share": round(per[entity] / total, 4),
                          "kinds": "+".join(sorted(kinds[payer]))}
    return out


def _with_station(sweep: Sweep, gas: Gas, stations: dict[str, dict]) -> Gas:
    """A verdict re-read once the gas stations are known. Another exchange's station
    among the payers is a conflict whatever the verdict was; the exchange's own
    station lifts an unlabelled verdict to `station`."""
    mine = [p for p in gas.payers if p in stations]
    other = [p for p in mine if stations[p]["entity"] != sweep.entity]
    if gas.verdict == "conflict" or not mine:
        return gas
    if not other and gas.verdict != "unlabelled":
        return gas
    payer = _most(other or mine, gas)
    return replace(gas, verdict="conflict" if other else "station", payer=payer,
                   payer_entity=stations[payer]["entity"], kinds=gas.kinds_by_payer[payer])


def _warm(workers: int, items: list, fetch: Callable, stage: str, progress) -> None:
    """Fetch every item's listing with a thread pool so the pass that follows reads
    the cache. Failures are left for that pass to meet again and count."""
    if workers <= 1 or not items:
        return
    done, lock = [0], threading.Lock()

    def one(item) -> None:
        try:
            fetch(item)
        except ProviderError:
            pass
        with lock:
            done[0] += 1
            if progress:
                progress(stage, done[0], len(items))

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(one, items))


def discover(chain: str, seed_provider, candidate_provider, labels,
             cfg: CrawlConfig = CrawlConfig(),
             progress: Callable[[str, int, int], None] | None = None,
             workers: int = 1) -> DiscoveryResult:
    """`seed_provider` pages deep into a busy wallet's inbound listing;
    `candidate_provider` reads one short page per candidate. `labels` answers
    `seeds(chain)` and `lookup_many(pairs)`.

    Stats are kept per exchange whose wallet surfaced the candidate, so in every row
    candidates = fired + rejected + errors and fired = derived + conflict + known.
    `totals["labels_by_exchange"]` counts the derived labels by the exchange they name
    (the same thing unless an address pays into two exchanges)."""
    result = DiscoveryResult(chain, cfg.as_dict())
    seeds = [s for s in labels.seeds(chain)
             if cfg.entities is None or s.entity in cfg.entities]
    _warm(workers, seeds, lambda s: _stable_rows(seed_provider, s.address, "in",
                                                 cfg.window_start, cfg.seed_limit),
          "fetching seed wallets", progress)
    stats: dict[str, dict] = {}
    found_by: dict[str, str] = {}                 # candidate -> exchange whose seed saw it
    for i, seed in enumerate(seeds):
        st = stats.setdefault(seed.entity, _new_stats())
        st["seeds"] += 1
        if progress:
            progress("seeds", i + 1, len(seeds))
        try:
            rows, _ = _stable_rows(seed_provider, seed.address, "in", cfg.window_start,
                                   cfg.seed_limit)
        except ProviderError:
            st["seed_errors"] += 1
            continue
        rows = [t for t in rows if t.amount_usd >= cfg.rules.dust]
        st["inbound_rows"] += len(rows)
        st["active_seeds"] += bool(rows)
        senders = list(dict.fromkeys(t.from_addr for t in rows))
        known = labels.lookup_many({(a, chain) for a in senders})
        fresh = [a for a in senders if not is_seed(known.get((a, chain)))]
        st["labelled_senders"] += len(senders) - len(fresh)
        for a in fresh[:cfg.max_candidates]:
            found_by.setdefault(a, seed.entity)
    for entity in stats:
        stats[entity]["candidates"] = sum(1 for e in found_by.values() if e == entity)

    def reject(address: str, reason: str) -> None:
        rejected = stats[found_by[address]]["rejected"]
        rejected[reason] = rejected.get(reason, 0) + 1

    since = cfg.window_start - timedelta(days=cfg.lookback_days)
    candidates = sorted(found_by)
    _warm(workers, candidates, lambda a: _stable_rows(candidate_provider, a, "both", since,
                                                      cfg.candidate_limit),
          "fetching candidates", progress)
    swept: dict[str, tuple[Sweep, dict, bool]] = {}
    for i, address in enumerate(candidates):
        if progress:
            progress("sweep rule", i + 1, len(candidates))
        try:
            rows, complete = _stable_rows(candidate_provider, address, "both", since,
                                          cfg.candidate_limit)
        except ProviderError:
            stats[found_by[address]]["errors"] += 1
            continue
        near = {a for t in rows for a in (t.from_addr, t.to_addr)}
        lab = {a: l for (a, _), l in labels.lookup_many({(a, chain) for a in near}).items()}
        sweep = sweep_rule(address, rows, lab, cfg.rules)
        if not sweep.fired:
            reject(address, sweep.reason)
        elif cfg.entities is not None and sweep.entity not in cfg.entities:
            reject(address, "forwards to an exchange outside this run")
        else:
            swept[address] = (sweep, lab, complete)

    _warm(workers, list(swept), lambda a: candidate_provider.gas_events(a, since=since),
          "fetching gas listings", progress)
    fired: dict[str, tuple[Sweep, Gas, object, bool]] = {}
    for i, (address, (sweep, lab, complete)) in enumerate(swept.items()):
        if progress:
            progress("gas rule", i + 1, len(swept))
        try:
            events = candidate_provider.gas_events(address, since=since)
        except ProviderError:
            stats[found_by[address]]["errors"] += 1
            continue
        payers = {e.payer for e in events} | {t.fee_payer for t in sweep.sweeps if t.fee_payer}
        lab.update({a: l for (a, _), l in
                    labels.lookup_many({(a, chain) for a in payers}).items()})
        gas = gas_rule(address, sweep.sweeps, events, lab, sweep.entity, cfg.rules)
        fired[address] = (sweep, gas, lab.get(address), complete)

    stations = _stations(fired, chain, cfg.rules)
    result.stations = list(stations.values())
    cut = (cfg.candidate_limit, since.strftime("%Y-%m-%d"))
    for address, (sweep, gas, existing, complete) in fired.items():
        gas = _with_station(sweep, gas, stations)
        decision = decide(sweep, gas.verdict, existing)
        result.findings.append(_finding(chain, sweep, gas, decision,
                                        None if complete else cut))
    result.findings.sort(key=lambda f: (f.entity, f.address))

    delays: dict[str, list[float]] = defaultdict(list)
    by_exchange: Counter = Counter()
    for f in result.findings:
        st = stats[found_by[f.address]]
        st["fired"] += 1
        st[f.status] += 1
        st["by_gas"][f.gas_verdict] = st["by_gas"].get(f.gas_verdict, 0) + 1
        if f.median_delay_s is not None:
            delays[found_by[f.address]].append(f.median_delay_s)
        if f.status == "derived":
            st["by_rule"][f.rule] = st["by_rule"].get(f.rule, 0) + 1
            by_exchange[f.entity] += 1
    for entity, st in stats.items():
        st["median_sweep_delay_s"] = median(delays[entity]) if delays[entity] else None
        for key in ("by_rule", "by_gas", "rejected"):
            st[key] = dict(sorted(st[key].items()))
    result.stats = dict(sorted(stats.items()))
    result.totals = {k: sum(st[k] for st in stats.values())
                     for k in ("seeds", "active_seeds", "inbound_rows", "candidates", "fired",
                               "derived", "conflict", "known", "errors", "seed_errors")}
    result.totals["stations"] = len(result.stations)
    result.totals["labels_by_exchange"] = dict(sorted(by_exchange.items()))
    return result


def _finding(chain: str, sweep: Sweep, gas: Gas, decision,
             cut: tuple[int, str] | None) -> Finding:
    first: Transfer = min(sweep.sweeps, key=lambda t: (t.block_time, t.tx_hash))
    last = max(t.block_time for t in sweep.sweeps)
    return Finding(
        address=sweep.address, chain=chain, entity=sweep.entity,
        category=sweep.target_category,     # the category of the wallet it sweeps to
        kind="deposit", status=decision.status, rule=decision.rule,
        confidence=decision.confidence, evidence=evidence_text(sweep, gas, decision, cut),
        conflict=decision.conflict, sweep_target=sweep.target, target_tier=sweep.target_tier,
        asset=sweep.asset, share=round(float(sweep.share), 4), received=str(sweep.received),
        forwarded=str(sweep.forwarded), n_deposits=sweep.n_deposits,
        n_senders=sweep.n_senders, n_sweeps=sweep.n_sweeps,
        median_delay_s=sweep.median_delay_s, gas_verdict=gas.verdict, gas_payer=gas.payer,
        gas_payer_entity=gas.payer_entity, gas_kinds="+".join(gas.kinds), n_paid=gas.n_paid,
        first_sweep_tx=first.tx_hash,
        last_sweep_time=last.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        complete=cut is None and gas.complete)
