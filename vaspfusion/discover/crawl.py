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
findings are sorted, so `OFFLINE=1` replays to the same result.
"""
from __future__ import annotations

from collections import Counter, defaultdict
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
    complete: bool              # False: the listing was cut at candidate_limit


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
            "errors": 0, "by_rule": {}, "by_gas": {}, "rejected": {},
            "median_sweep_delay_s": None}


def _stable_rows(provider, address: str, direction: str, since, limit: int):
    """The address's stablecoin transfers, and whether that is all of them."""
    rows, complete = [], True
    for asset in provider.traceable_assets[:-1]:        # the native coin is last
        got = provider.transfers(address, direction, since=since, limit=limit, asset=asset)
        rows += got
        complete = complete and getattr(got, "complete", len(got) < limit)
    return sort_transfers(rows), complete


def _stations(fired: dict[str, tuple[Sweep, Gas, object, bool]], chain: str,
              rules: DiscoverConfig) -> dict[str, dict]:
    served: dict[str, Counter] = defaultdict(Counter)
    kinds: dict[str, set[str]] = defaultdict(set)
    for sweep, gas, _, _ in fired.values():
        if gas.verdict != "unlabelled":
            continue
        for payer in gas.payers:
            served[payer][sweep.entity] += 1
        kinds[gas.payer] |= set(gas.kinds)
    out = {}
    for payer, per in sorted(served.items()):
        total = sum(per.values())
        entity = min(per, key=lambda e: (-per[e], e))
        if total >= rules.min_station and per[entity] / total >= rules.station_share:
            out[payer] = {"address": payer, "chain": chain, "entity": entity,
                          "addresses": total, "share": round(per[entity] / total, 4),
                          "kinds": "+".join(sorted(kinds[payer]))}
    return out


def _with_station(sweep: Sweep, gas: Gas, stations: dict[str, dict]) -> Gas:
    """An unlabelled verdict, re-read once the gas stations are known."""
    if gas.verdict != "unlabelled":
        return gas
    mine = [p for p in gas.payers if p in stations]
    if not mine:
        return gas
    other = [p for p in mine if stations[p]["entity"] != sweep.entity]
    payer = min(other or mine, key=lambda p: (-gas.payers[p], p))
    return replace(gas, verdict="conflict" if other else "station", payer=payer,
                   payer_entity=stations[payer]["entity"])


def discover(chain: str, seed_provider, candidate_provider, labels,
             cfg: CrawlConfig = CrawlConfig(),
             progress: Callable[[str, int, int], None] | None = None) -> DiscoveryResult:
    """`seed_provider` pages deep into a busy wallet's inbound listing;
    `candidate_provider` reads one short page per candidate. `labels` answers
    `seeds(chain)` and `lookup_many(pairs)`."""
    result = DiscoveryResult(chain, cfg.as_dict())
    seeds = [s for s in labels.seeds(chain)
             if cfg.entities is None or s.entity in cfg.entities]
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
            st["errors"] += 1
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

    since = cfg.window_start - timedelta(days=cfg.lookback_days)
    fired: dict[str, tuple[Sweep, Gas, object, bool]] = {}
    for i, address in enumerate(sorted(found_by)):
        st = stats[found_by[address]]
        if progress:
            progress("candidates", i + 1, len(found_by))
        try:
            rows, complete = _stable_rows(candidate_provider, address, "both", since,
                                          cfg.candidate_limit)
            near = {a for t in rows for a in (t.from_addr, t.to_addr)}
            lab = {a: l for (a, _), l in
                   labels.lookup_many({(a, chain) for a in near}).items()}
            sweep = sweep_rule(address, rows, lab, cfg.rules)
            if not sweep.fired:
                st["rejected"][sweep.reason] = st["rejected"].get(sweep.reason, 0) + 1
                continue
            events = candidate_provider.gas_events(address, since=since)
            payers = {e.payer for e in events} | {t.fee_payer for t in sweep.sweeps
                                                  if t.fee_payer}
            lab.update({a: l for (a, _), l in
                        labels.lookup_many({(a, chain) for a in payers}).items()})
            gas = gas_rule(address, sweep.sweeps, events, lab, sweep.entity, cfg.rules)
        except ProviderError:
            st["errors"] += 1
            continue
        fired[address] = (sweep, gas, lab.get(address), complete)

    stations = _stations(fired, chain, cfg.rules)
    result.stations = list(stations.values())
    for address, (sweep, gas, existing, complete) in fired.items():
        gas = _with_station(sweep, gas, stations)
        decision = decide(sweep, gas.verdict, existing)
        result.findings.append(_finding(chain, sweep, gas, decision, complete))
    result.findings.sort(key=lambda f: (f.entity, f.address))

    for f in result.findings:
        st = stats.setdefault(f.entity, _new_stats())
        st["fired"] += 1
        st[f.status] += 1
        st["by_gas"][f.gas_verdict] = st["by_gas"].get(f.gas_verdict, 0) + 1
        if f.status == "derived":
            st["by_rule"][f.rule] = st["by_rule"].get(f.rule, 0) + 1
    for entity, st in stats.items():
        delays = [f.median_delay_s for f in result.findings
                  if f.entity == entity and f.median_delay_s is not None]
        st["median_sweep_delay_s"] = median(delays) if delays else None
        for key in ("by_rule", "by_gas", "rejected"):
            st[key] = dict(sorted(st[key].items()))
    result.stats = dict(sorted(stats.items()))
    result.totals = {k: sum(st[k] for st in stats.values())
                     for k in ("seeds", "active_seeds", "inbound_rows", "candidates", "fired",
                               "derived", "conflict", "known", "errors")}
    result.totals["stations"] = len(result.stations)
    return result


def _finding(chain: str, sweep: Sweep, gas: Gas, decision, complete: bool) -> Finding:
    first: Transfer = min(sweep.sweeps, key=lambda t: (t.block_time, t.tx_hash))
    last = max(t.block_time for t in sweep.sweeps)
    return Finding(
        address=sweep.address, chain=chain, entity=sweep.entity,
        category=sweep.target_category,     # the category of the wallet it sweeps to
        kind="deposit", status=decision.status, rule=decision.rule,
        confidence=decision.confidence, evidence=evidence_text(sweep, gas, decision),
        conflict=decision.conflict, sweep_target=sweep.target, target_tier=sweep.target_tier,
        asset=sweep.asset, share=round(float(sweep.share), 4), received=str(sweep.received),
        forwarded=str(sweep.forwarded), n_deposits=sweep.n_deposits,
        n_senders=sweep.n_senders, n_sweeps=sweep.n_sweeps,
        median_delay_s=sweep.median_delay_s, gas_verdict=gas.verdict, gas_payer=gas.payer,
        gas_payer_entity=gas.payer_entity, gas_kinds="+".join(gas.kinds), n_paid=gas.n_paid,
        first_sweep_tx=first.tx_hash,
        last_sweep_time=last.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        complete=complete)
