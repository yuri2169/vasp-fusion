"""How good are the discovery rules? A hold-out test on explorer-tagged addresses (RQ1).

Truth: addresses an explorer tagged as an exchange's deposit address. Those tags are
never seeds (rules.is_seed), and the address under test is judged without its own
label, so the rules have to rediscover it from the exchange's other wallets alone.

* Positives: a seeded sample of one exchange's tagged deposit addresses.
  recall = rediscovered for that exchange / positives.
* Negatives: a seeded sample of tagged addresses that are not deposit addresses,
  half of them exchange wallets (the hard case: they also move funds to exchange
  wallets) and half anything else. false-positive rate = rule fired / negatives.
* precision_in_sample = right / all the rule fired on. It depends on the mix of the
  sample, so the false-positive rates are the numbers to carry elsewhere.

Each address is read once (its earliest `limit` transfers, all assets) through the
cache, so the run replays offline. No rate is reported for an empty group.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field

from ..chains.base import ProviderError
from ..labels.normalize import VASP_CATEGORIES
from .rules import DiscoverConfig, decide, gas_rule, sweep_rule

NO_STABLE = "no stablecoin transfers"


@dataclass(frozen=True)
class EvalConfig:
    chain: str = "ethereum"
    entity: str = "Bitget"
    n_positive: int = 300
    n_negative: int = 300          # half exchange wallets, half other tagged addresses
    seed: int = 26182
    limit: int = 200               # transfers read per address and listing
    rules: DiscoverConfig = DiscoverConfig()

    def as_dict(self) -> dict:
        d = asdict(self)
        d["rules"]["dust"] = str(self.rules.dust)
        return d


@dataclass
class EvalReport:
    config: dict
    metrics: dict = field(default_factory=dict)
    rows: list[dict] = field(default_factory=list)


def sample(labels, cfg: EvalConfig) -> tuple[list[str], list[str], list[str]]:
    """(positives, negative exchange wallets, other negatives), drawn with `cfg.seed`."""
    tagged = labels.by_tier(cfg.chain, "explorer_tag")
    positives = sorted(l.address for l in tagged
                       if l.kind == "deposit" and l.entity == cfg.entity)
    rest = [l for l in tagged if l.kind != "deposit"]
    exchange = sorted(l.address for l in rest if l.category in VASP_CATEGORIES)
    other = sorted(l.address for l in rest if l.category not in VASP_CATEGORIES)
    rng = random.Random(cfg.seed)

    def draw(population: list[str], n: int) -> list[str]:
        return sorted(rng.sample(population, min(n, len(population))))

    return (draw(positives, cfg.n_positive), draw(exchange, cfg.n_negative // 2),
            draw(other, cfg.n_negative - cfg.n_negative // 2))


def _judge(provider, labels, address: str, cfg: EvalConfig) -> dict:
    """Run both rules on one address, blind to its own label."""
    chain = cfg.chain
    rows = provider.transfers(address, "both", limit=cfg.limit)
    stable = [t for t in rows if t.amount_usd is not None]
    out = {"fired": False, "entity": None, "rule": None, "gas": None, "reason": None,
           "status": None, "has_stable": bool(stable)}
    if not stable:
        out["reason"] = NO_STABLE
        return out
    near = {a for t in stable for a in (t.from_addr, t.to_addr)} - {address}
    lab = {a: l for (a, _), l in labels.lookup_many({(a, chain) for a in near}).items()}
    sweep = sweep_rule(address, stable, lab, cfg.rules)
    out["entity"], out["reason"] = sweep.entity, sweep.reason
    if not sweep.fired:
        return out
    events = provider.gas_events(address, limit=cfg.limit)
    payers = {e.payer for e in events} - {address}
    lab.update({a: l for (a, _), l in labels.lookup_many({(a, chain) for a in payers}).items()})
    gas = gas_rule(address, sweep.sweeps, events, lab, sweep.entity, cfg.rules)
    decision = decide(sweep, gas.verdict, existing=None)
    out.update(fired=True, rule=decision.rule, gas=gas.verdict, status=decision.status,
               reason=decision.conflict)
    return out


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


def evaluate(provider, labels, positives: list[str], neg_exchange: list[str],
             neg_other: list[str], cfg: EvalConfig = EvalConfig(), progress=None) -> EvalReport:
    report = EvalReport(cfg.as_dict())
    groups = [("deposit", positives), ("exchange_wallet", neg_exchange),
              ("other_tagged", neg_other)]
    todo = [(truth, a) for truth, addresses in groups for a in addresses]
    tags = labels.lookup_many({(a, cfg.chain) for _, a in todo})
    errors = 0
    for i, (truth, address) in enumerate(todo):
        if progress:
            progress("addresses", i + 1, len(todo))
        tag = tags.get((address, cfg.chain))
        row = {"address": address, "truth": truth, "tag": tag.entity if tag else None,
               "outcome": "error", "entity": None, "rule": None, "gas": None, "reason": None}
        try:
            j = _judge(provider, labels, address, cfg)
        except ProviderError as e:
            errors += 1
            row["reason"] = str(e)[:200]
            report.rows.append(row)
            continue
        row.update(entity=j["entity"], rule=j["rule"], gas=j["gas"], reason=j["reason"])
        row["_stable"] = j["has_stable"]
        if not j["fired"]:
            row["outcome"] = "missed" if truth == "deposit" else "true_negative"
        elif j["status"] == "conflict":
            row["outcome"] = "conflict"
        elif truth != "deposit":
            row["outcome"] = "false_positive"
        else:
            row["outcome"] = "derived" if j["entity"] == cfg.entity else "wrong_entity"
        report.rows.append(row)

    def count(truth: str, *outcomes: str) -> int:
        return sum(1 for r in report.rows if r["truth"] == truth and r["outcome"] in outcomes)

    def size(truth: str) -> int:
        return sum(1 for r in report.rows if r["truth"] == truth and r["outcome"] != "error")

    pos = [r for r in report.rows if r["truth"] == "deposit" and r["outcome"] != "error"]
    tp, wrong = count("deposit", "derived"), count("deposit", "wrong_entity")
    active = sum(1 for r in pos if r["_stable"])
    fp_rows = [r for r in report.rows if r["outcome"] == "false_positive"]
    by_rule: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    for r in pos:
        if r["outcome"] == "derived":
            by_rule[r["rule"]] = by_rule.get(r["rule"], 0) + 1
        elif r["outcome"] == "missed":
            by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    report.metrics = {
        "positives": len(pos), "true_positives": tp, "wrong_entity": wrong,
        "conflicts": count("deposit", "conflict"), "missed": count("deposit", "missed"),
        "recall": _rate(tp, len(pos)),
        "positives_with_stablecoin_activity": active,
        "recall_with_stablecoin_activity": _rate(tp, active),
        "entity_precision": _rate(tp, tp + wrong),
        "true_positives_by_rule": dict(sorted(by_rule.items())),
        "missed_by_reason": dict(sorted(by_reason.items())),
        "negatives": size("exchange_wallet") + size("other_tagged"),
        "false_positives": len(fp_rows),
        "false_positives_naming_the_tagged_exchange":
            sum(1 for r in fp_rows if r["entity"] == r["tag"]),
        "false_positive_rate": {
            "exchange_wallets": _rate(count("exchange_wallet", "false_positive"),
                                      size("exchange_wallet")),
            "other_tagged": _rate(count("other_tagged", "false_positive"),
                                  size("other_tagged"))},
        "precision_in_sample": _rate(tp, tp + wrong + len(fp_rows)),
        "errors": errors,
    }
    for r in report.rows:
        r.pop("_stable", None)
    return report
