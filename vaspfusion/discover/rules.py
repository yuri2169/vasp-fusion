"""The two rules that turn an exchange's labelled wallets into derived deposit addresses.

Seed: a label with a VASP category that is neither derived nor itself a deposit
address (so derived labels never breed further labels).

Rule 1, sweep. Over an address's stablecoin transfers, deposits enter a
first-in-first-out queue and every outflow consumes it. A consumed part counts as
forwarded to exchange E when the outflow goes to a seed of E within `max_hours`
of the part's arrival. `received` is what arrived before the last outflow (later
deposits are not swept yet); outflow beyond the queue is balance from before the
listing and is ignored. The rule fires when forwarded / received >= `min_share`.

Rule 2, gas payer. Exchanges cover the network fee of their own deposit addresses:
on Tron they delegate energy or send TRX just before the sweep. Whoever did that
within `gas_window_s` before a sweep (or signed the sweep) is its payer. A payer
that is a seed of the same exchange confirms rule 1; a seed of another exchange
is a conflict, which is recorded and never becomes a label.

The confidence is the attribution weight of the sweep target's label tier times
a factor for how much the gas rule adds. It is hand-set, not calibrated (B6).
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median

from ..attribute.rules import TIER_WEIGHT
from ..chains.base import GasEvent, Transfer
from ..explain import fmt
from ..labels.lookup import Label
from ..labels.normalize import VASP_CATEGORIES

ZERO = Decimal(0)
GAS_FACTOR = {"confirmed": 0.95, "station": 0.90, "unlabelled": 0.80, "other_label": 0.80,
              "none": 0.80}
RULE_NAME = {"confirmed": "sweep+gas", "station": "sweep+station"}


@dataclass(frozen=True)
class DiscoverConfig:
    min_share: float = 0.90          # X: share of what it received that must be forwarded
    max_hours: float = 24.0          # T: a part must leave within this long of arriving
    min_senders: int = 1             # distinct depositors seen before the last sweep
    dust: Decimal = Decimal("0.1")   # smaller rows are address-poisoning spam
    gas_window_s: int = 3600         # how long before a sweep its gas may have been paid
    min_station: int = 10            # deposit addresses an unlabelled payer must serve
    station_share: float = 0.95      # ... and the share of them that are one exchange's


def is_seed(label: Label | None) -> bool:
    return (label is not None and label.category in VASP_CATEGORIES
            and label.tier != "derived" and label.kind != "deposit")


@dataclass
class Sweep:
    address: str
    fired: bool = False
    reason: str | None = None        # why it did not fire
    entity: str | None = None
    target: str | None = None        # the seed wallet that took the most
    target_tier: str | None = None
    target_category: str | None = None
    asset: str | None = None
    share: Decimal = ZERO
    received: Decimal = ZERO
    forwarded: Decimal = ZERO
    pending: Decimal = ZERO          # arrived after the last outflow
    n_deposits: int = 0
    n_senders: int = 0
    n_sweeps: int = 0
    median_delay_s: float | None = None
    sweeps: list[Transfer] = field(default_factory=list)
    other_entities: dict[str, Decimal] = field(default_factory=dict)


@dataclass
class Gas:
    # confirmed | conflict | unlabelled | other_label | none | station
    verdict: str
    payer: str | None = None
    payer_entity: str | None = None
    kinds: tuple[str, ...] = ()
    n_paid: int = 0                  # sweeps with at least one outside payer
    n_sweeps: int = 0
    payers: dict[str, int] = field(default_factory=dict)   # payer -> sweeps it paid for
    kinds_by_payer: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # payers that carry a label which is not an exchange wallet's (sanctioned, a service,
    # a tagged deposit address): named in the evidence, and never a gas station
    other_labels: dict[str, str] = field(default_factory=dict)
    seed_payers: dict[str, str] = field(default_factory=dict)   # payer -> its exchange
    complete: bool = True            # False: the gas listing was cut short


@dataclass(frozen=True)
class Decision:
    status: str                      # derived | conflict | known
    rule: str                        # sweep | sweep+gas | sweep+station
    confidence: float | None
    conflict: str | None = None


def sweep_rule(address: str, rows: list[Transfer], labels: dict[str, Label],
               cfg: DiscoverConfig = DiscoverConfig()) -> Sweep:
    rows = [t for t in rows if t.amount_usd is not None and t.amount_usd >= cfg.dust
            and address in (t.from_addr, t.to_addr) and t.from_addr != t.to_addr]
    # a deposit and a sweep in the same second: the deposit came first. The rest of the
    # key only makes the order total, so the result never depends on the input order
    rows.sort(key=lambda t: (t.block_time, t.from_addr == address, t.tx_hash, t.to_addr,
                             t.from_addr, t.asset, t.amount))
    out = Sweep(address)
    outs = [i for i, t in enumerate(rows) if t.from_addr == address]
    to_seed: dict[str, list[Transfer]] = defaultdict(list)
    for i in outs:
        lab = labels.get(rows[i].to_addr)
        if is_seed(lab):
            to_seed[lab.entity].append(rows[i])
    if not to_seed:
        out.reason = "sends nothing to a labelled exchange wallet"
        return out

    last_out = outs[-1]
    deposits = [t for t in rows[:last_out] if t.to_addr == address]
    out.pending = sum((t.amount_usd for t in rows[last_out:] if t.to_addr == address), ZERO)
    out.received = sum((t.amount_usd for t in deposits), ZERO)
    out.n_deposits, out.n_senders = len(deposits), len({t.from_addr for t in deposits})

    queue: deque[list] = deque()                 # [amount left, arrival time]
    matched: Counter = Counter()                 # entity -> amount, any delay
    in_time: Counter = Counter()                 # entity -> amount within max_hours
    delays: dict[str, list[float]] = defaultdict(list)
    for t in rows[:last_out + 1]:
        if t.to_addr == address:
            queue.append([t.amount_usd, t.block_time])
            continue
        lab = labels.get(t.to_addr)
        entity = lab.entity if is_seed(lab) else None
        left = t.amount_usd
        while left > 0 and queue:
            part = min(left, queue[0][0])
            waited = (t.block_time - queue[0][1]).total_seconds()
            if entity is not None:
                matched[entity] += part
                if waited <= cfg.max_hours * 3600:
                    in_time[entity] += part
                    delays[entity].append(waited)
            queue[0][0] -= part
            left -= part
            if queue[0][0] == 0:
                queue.popleft()

    totals = {e: sum((t.amount_usd for t in ts), ZERO) for e, ts in to_seed.items()}
    entity = min(totals, key=lambda e: (-totals[e], e))
    by_target: Counter = Counter()
    for t in to_seed[entity]:
        by_target[t.to_addr] += t.amount_usd
    out.entity = entity
    out.target = min(by_target, key=lambda a: (-by_target[a], a))
    out.target_tier = labels[out.target].tier
    out.target_category = labels[out.target].category
    out.sweeps = to_seed[entity]
    out.n_sweeps = len(out.sweeps)
    assets = {t.asset for t in out.sweeps}
    out.asset = assets.pop() if len(assets) == 1 else "stablecoins"
    out.forwarded = in_time[entity]
    out.other_entities = {e: matched[e] for e in sorted(totals) if e != entity and matched[e]}
    out.median_delay_s = median(delays[entity]) if delays[entity] else None
    if out.received == 0:
        out.reason = "no deposit seen before a sweep"
        return out
    out.share = out.forwarded / out.received
    if out.share < Decimal(str(cfg.min_share)):
        out.reason = f"forwards under {fmt.pct(cfg.min_share)} of what it receives"
    elif out.n_senders < cfg.min_senders:
        out.reason = f"fewer than {cfg.min_senders} distinct senders"
    else:
        out.fired = True
    return out


def gas_rule(address: str, sweeps: list[Transfer], events: list[GasEvent],
             labels: dict[str, Label], entity: str,
             cfg: DiscoverConfig = DiscoverConfig()) -> Gas:
    payers: Counter = Counter()
    kinds: dict[str, set[str]] = defaultdict(set)
    n_paid = 0
    for s in sweeps:
        found: set[str] = set()
        if s.fee_payer is not None and s.fee_payer != address:
            found.add(s.fee_payer)
            kinds[s.fee_payer].add("signer")
        for e in events:
            ahead = (s.block_time - e.time).total_seconds()
            if e.kind == "signer":       # only the sweep's own signer paid for the sweep
                paid = e.tx_hash == s.tx_hash
            else:
                paid = 0 <= ahead <= cfg.gas_window_s
            if e.payer != address and paid:
                found.add(e.payer)
                kinds[e.payer].add(e.kind)
        n_paid += bool(found)
        payers.update(found)
    gas = Gas("none", n_paid=n_paid, n_sweeps=len(sweeps), payers=dict(sorted(payers.items())),
              kinds_by_payer={p: tuple(sorted(kinds[p])) for p in sorted(payers)},
              complete=getattr(events, "complete", True))
    if not payers:
        return gas

    def owner(p: str) -> str | None:
        lab = labels.get(p)
        return lab.entity if is_seed(lab) else None

    def most(group: list[str]) -> str:
        return min(group, key=lambda p: (-payers[p], p))

    for p in sorted(payers):
        lab = labels.get(p)
        if lab is not None and lab.tier != "derived" and not is_seed(lab):
            gas.other_labels[p] = f"{lab.entity} ({lab.category})"
    gas.seed_payers = {p: owner(p) for p in sorted(payers) if owner(p) is not None}
    other = [p for p in payers if owner(p) not in (None, entity)]
    same = [p for p in payers if owner(p) == entity]
    gas.payer = most(other or same or list(payers))
    gas.verdict = ("conflict" if other else "confirmed" if same
                   else "other_label" if gas.payer in gas.other_labels else "unlabelled")
    gas.payer_entity = owner(gas.payer)
    gas.kinds = gas.kinds_by_payer[gas.payer]
    return gas


def decide(sweep: Sweep, verdict: str, existing: Label | None) -> Decision:
    """`existing` is the address's own label, if it has one that we did not derive."""
    rule = RULE_NAME.get(verdict, "sweep")
    if existing is not None and existing.tier == "derived" and existing.entity != sweep.entity:
        return Decision("conflict", rule, None, f"an earlier run derived it as a "
                                                f"{existing.entity} deposit address")
    if existing is not None and existing.tier != "derived":
        if existing.entity == sweep.entity and existing.category in VASP_CATEGORIES:
            return Decision("known", rule, None)
        return Decision("conflict", rule, None, f"already labelled {existing.entity} "
                                                f"({existing.category}, {existing.tier})")
    if verdict == "conflict":
        return Decision("conflict", rule, None, "the rules name different exchanges")
    return Decision("derived", rule,
                    round(TIER_WEIGHT[sweep.target_tier] * GAS_FACTOR[verdict], 4))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def evidence_text(sweep: Sweep, gas: Gas, decision: Decision,
                  cut: tuple[int, str] | None = None) -> str:
    """What an officer reads next to a derived label: the numbers both rules used.
    `cut` = (rows read, since) when the address has more transfers than were read."""
    text = (f"Sweep rule: forwarded {fmt.pct(sweep.share)} of the "
            f"{fmt.amount(sweep.received, sweep.asset)} it received from "
            f"{_plural(sweep.n_senders, 'sender')} to {sweep.entity} wallet "
            f"{fmt.short(sweep.target)} ({fmt.tier_words(sweep.target_tier)}) in "
            f"{_plural(sweep.n_sweeps, 'sweep')}, typically "
            f"{fmt.duration(sweep.median_delay_s)} after arrival. ")
    if cut is not None:
        text += (f"Only its first {cut[0]} transfers since {cut[1]} were read; what it did "
                 "later is not covered. ")
    if not gas.complete:
        text += "Its gas listing was not read to the end. "
    if gas.payer is None:
        text += "Gas rule: no outside gas payer seen. "
    else:
        who = {"confirmed": f"labelled {gas.payer_entity}",
               "conflict": f"labelled {gas.payer_entity}",
               "station": f"derived as a {gas.payer_entity} gas station",
               "other_label": f"labelled {gas.other_labels.get(gas.payer)}",
               "unlabelled": "not labelled"}[gas.verdict]
        did = ("paid the energy" if {"energy", "bandwidth"} & set(gas.kinds)
               else "sent the fee money" if "native" in gas.kinds else "signed and paid")
        text += (f"Gas rule: {fmt.short(gas.payer)}, {who}, {did} for "
                 f"{gas.payers[gas.payer]} of {_plural(gas.n_sweeps, 'sweep')}. ")
    if decision.status == "conflict":
        return text + f"Conflict: {decision.conflict}. Not used as a label."
    if decision.status == "known":
        return text + "Already labelled for this exchange."
    text += {"sweep+gas": "Both rules agree. ",
             "sweep+station": "The payer serves this exchange's deposit addresses. ",
             "sweep": "Sweep rule only. "}[decision.rule]
    return text + f"Rule confidence {decision.confidence:.2f}, not calibrated."
