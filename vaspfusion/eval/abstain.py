"""Where to put the abstain threshold: measured on real wallets with a known answer.

There is no labelled set of "wallet -> the exchange it paid" cases. One is built by
hiding labels (a label hold-out):

* Wallets: a seeded sample of the real customers in the deposit model's dataset
  (artifacts/model_v1/<chain>/dataset.csv): wallets that paid an address the
  discovery rules derived as an exchange deposit address.
* Known answer: the exchanges the wallet paid directly according to the FULL label
  store (the trace with every label, candidates one hop away), plus the exchange
  whose deposit address put it in the dataset.
* Test: the wallet is traced again with every derived label hidden. That is the tool
  as it was before the deposit addresses were derived: it has to find the exchange
  through an unlabelled wallet. Every exchange it then reaches is one claim, with the
  rule confidence it would be shown with. A claim is right when the exchange is in
  the known answer.

The claims that matter are the ones made through unlabelled wallets (two hops or
more). A claim one hop away rests on a label that was not hidden, so it is right by
construction and is reported apart.

Each wallet is traced from the start of the discovery run that found it (`since`),
because derived labels only exist for that window: an older payment into a deposit
address nobody derived would be counted against the tool for no reason.

The test is strict on purpose. A claim that reached an exchange's wallet through a
wallet the rules did not derive counts as wrong, although that wallet may well be a
deposit address the rules missed. The risk here is an upper bound on "named an
exchange the wallet did not pay".

What this set is not: every wallet in it is an exchange customer, so it says nothing
about wallets that never paid an exchange; and the confidence it sweeps is still
rule-set (label weight x hop decay x share factor), so the threshold it supports is
"measured on a hold-out", not "calibrated".
"""
from __future__ import annotations

import csv
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl

from ..attribute.rules import RuleConfig, attribute
from ..chains.base import ProviderError
from ..trace import TraceConfig, trace
from .selective import risk_controlled_threshold, risk_coverage

SEED = 26182
VERSION = "abstain_v1"
GRID = (0.30, 0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
COLUMNS = ["wallet", "exchange", "run", "known", "vasp", "rank", "hops", "share", "confidence",
           "direct", "correct"]


@dataclass(frozen=True)
class AbstainConfig:
    per_exchange: int = 40
    seed: int = SEED
    target_risk: float = 0.05
    delta: float = 0.05
    grid: tuple[float, ...] = GRID
    # the trace every case runs with; who funded the wallet never decides an outcome
    trace: TraceConfig = TraceConfig(max_hops=3, inbound_hops=0)
    rules: RuleConfig = RuleConfig()


class WithoutTier:
    """A label lookup that does not know the labels of one tier."""

    def __init__(self, labels, tier: str = "derived"):
        self.labels, self.tier = labels, tier

    def lookup_many(self, pairs):
        return {k: v for k, v in self.labels.lookup_many(pairs).items() if v.tier != self.tier}


def sample_wallets(dataset: pl.DataFrame, cfg: AbstainConfig = AbstainConfig()
                   ) -> list[tuple[str, str, str]]:
    """(wallet, the exchange whose deposit address it paid, the discovery run that found
    it): up to `per_exchange` customers of each exchange, drawn with the seed."""
    customers = dataset.filter(pl.col("source") == "customer").sort("address")
    picked: list[tuple[str, str, str]] = []
    for exchange in sorted(set(customers["group"].to_list())):
        pool = customers.filter(pl.col("group") == exchange)
        runs = dict(pool.select("address", "run").iter_rows())
        rng = random.Random(f"{cfg.seed}:abstain:{exchange}")
        picked += [(a, exchange, runs[a])
                   for a in sorted(rng.sample(sorted(runs), min(cfg.per_exchange, len(runs))))]
    return picked


def claims_for(wallet: str, exchange: str, chain: str, provider, labels,
               cfg: AbstainConfig = AbstainConfig(), since: datetime | None = None,
               run: str = "") -> list[dict]:
    """The rows of one wallet: one per exchange the label-hidden trace reaches, or a
    single row with no exchange when it reaches none."""
    how = replace(cfg.trace, since=since)
    full = attribute(trace(wallet, chain, provider, labels, how), cfg.rules)
    known = {exchange} | {c.vasp for c in full.candidates
                          if c.direction == "outbound" and c.hops_min == 1}
    hidden = attribute(trace(wallet, chain, provider, WithoutTier(labels), how), cfg.rules)
    base = {"wallet": wallet, "exchange": exchange, "run": run,
            "known": "|".join(sorted(known))}
    rows = [{**base, "vasp": c.vasp, "rank": c.proximity_rank, "hops": c.hops_min,
             "share": round(float(c.share), 4), "confidence": c.confidence,
             "direct": int(c.hops_min == 1), "correct": int(c.vasp in known)}
            for c in hidden.candidates if c.direction == "outbound" and c.hops > 0]
    return rows or [{**base, "vasp": "", "rank": "", "hops": "", "share": "", "confidence": "",
                     "direct": "", "correct": ""}]


def collect(wallets: list[tuple[str, str, str]], chain: str, provider, open_labels,
            cfg: AbstainConfig = AbstainConfig(), workers: int = 1, progress=None,
            since: dict[str, datetime] | None = None) -> tuple[list[dict], dict]:
    """Every wallet's rows. `open_labels()` gives a label store; each worker thread opens
    its own. `since`: discovery run -> the start of what it read. A wallet's rows depend
    only on the pages read, so the order the threads finish in changes nothing."""
    since = since or {}
    local = threading.local()
    done, lock, errors = [0], threading.Lock(), []

    def one(item) -> list[dict]:
        if not hasattr(local, "labels"):
            local.labels = open_labels()
        try:
            rows = claims_for(item[0], item[1], chain, provider, local.labels, cfg,
                              since.get(item[2]), item[2])
        except ProviderError as e:
            rows = []
            with lock:
                errors.append((item[0], str(e)))
        with lock:
            done[0] += 1
            if progress:
                progress("wallets", done[0], len(wallets))
        return rows

    if workers <= 1:
        parts = [one(w) for w in wallets]
    else:
        with ThreadPoolExecutor(workers) as pool:
            parts = list(pool.map(one, wallets))
    rows = sorted((r for part in parts for r in part),
                  key=lambda r: (r["wallet"], r["rank"] if r["rank"] != "" else 0))
    return rows, {"wallets_sampled": len(wallets), "wallets_read": len(wallets) - len(errors),
                  "errors": len(errors)}


# ------------------------------------------------------------------ the CSV
def write_claims(path: Path | str, rows: list[dict]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([r[c] for c in COLUMNS])
    return path


def read_claims(path: Path | str) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        if r["vasp"]:
            r.update(rank=int(r["rank"]), hops=int(r["hops"]), share=float(r["share"]),
                     confidence=float(r["confidence"]), direct=int(r["direct"]),
                     correct=int(r["correct"]))
    return rows


# ------------------------------------------------------------------ the measurement
def _cases_at(by_wallet: dict[str, list[dict]], t: float) -> dict:
    """What the outcome rule does at bar `t`: the nearest claim at or above it is named."""
    named = right = 0
    for claims in by_wallet.values():
        clearing = [c for c in claims if c["confidence"] >= t]
        if clearing:
            named += 1
            right += min(clearing, key=lambda c: c["rank"])["correct"]
    n = len(by_wallet)
    return {"threshold": t, "wallets": n, "named": named, "right": right,
            "wrong": named - right, "abstained": n - named,
            "coverage": round(named / n, 4) if n else None,
            "risk": round((named - right) / named, 4) if named else None}


def _selective(claims: list[dict], cfg: AbstainConfig) -> dict:
    conf = np.array([c["confidence"] for c in claims], dtype=float)
    ok = np.array([c["correct"] for c in claims], dtype=bool)
    return {"claims": len(claims), "right": int(ok.sum()), "wrong": int((~ok).sum()),
            "risk_coverage": risk_coverage(conf, ok, len(claims)),
            "threshold": risk_controlled_threshold(conf, ok, cfg.target_risk, cfg.delta,
                                                   cfg.grid)}


def notes(m: dict) -> list[str]:
    ind, cur = m["through_unlabelled"], m["at_current"]
    t = ind["threshold"]
    said = [
        f"Validation set: {m['wallets']} real {m['chain'].title()} wallets that paid an address "
        "the discovery rules derived as an exchange deposit address (a seeded sample of the "
        "deposit model's customers). Known answer: the exchanges each paid directly, from the "
        "full label store.",
        "Test: each wallet traced from the start of its discovery window with every derived "
        "label hidden, so an exchange has to be "
        f"found through an unlabelled wallet. {ind['claims']} such claims were made, "
        f"{ind['right']} right and {ind['wrong']} wrong.",
        "Strict on purpose: a claim that reached an exchange's wallet through a wallet the "
        "rules did not derive counts as wrong, so the risk is an upper bound.",
    ]
    if t["attainable"]:
        said.append(
            f"Lowest bar that keeps the risk under {t['target_risk']:.0%} with "
            f"{1 - t['delta']:.0%} confidence: {t['threshold']:.2f} ({t['errors']} wrong of "
            f"{t['n_answered']} answered; upper bound {t['risk_upper_bound']:.1%}).")
    else:
        said.append(f"No bar on the grid keeps the risk under {t['target_risk']:.0%} with "
                    f"{1 - t['delta']:.0%} confidence on this set.")
    said.append(
        f"At the bar in use, {m['current_threshold']:.2f}: {cur['claims']['n_answered']} claims "
        f"answered, {cur['claims']['errors']} wrong (risk "
        f"{(cur['claims']['risk'] or 0):.1%}, upper bound "
        f"{cur['claims']['risk_upper_bound']:.1%}); of {cur['cases']['wallets']} wallets "
        f"{cur['cases']['named']} get an exchange named ({cur['cases']['wrong']} wrong) and "
        f"{cur['cases']['abstained']} abstain.")
    said.append("Not calibrated: the confidence swept here is rule-set (label weight x hop "
                "decay x share factor). And every wallet in the set is an exchange customer, "
                "so nothing here measures wallets that never paid an exchange.")
    return said


def measure(rows: list[dict], chain: str, cfg: AbstainConfig = AbstainConfig(),
            current: float | None = None) -> dict:
    """claims.csv -> validation.json."""
    current = cfg.rules.attribute_min if current is None else current
    claims = [r for r in rows if r["vasp"]]
    indirect = [c for c in claims if not c["direct"]]
    by_wallet: dict[str, list[dict]] = {r["wallet"]: [] for r in rows}
    for c in claims:
        by_wallet[c["wallet"]].append(c)
    through = _selective(indirect, cfg)
    every = _selective(claims, cfg)
    at = next((g for g in through["threshold"]["grid"] if g["threshold"] == current), None)
    m = {
        "version": VERSION, "chain": chain, "seed": cfg.seed,
        "config": {"per_exchange": cfg.per_exchange, "target_risk": cfg.target_risk,
                   "delta": cfg.delta, "grid": list(cfg.grid), "max_hops": cfg.trace.max_hops,
                   "hidden_tier": "derived"},
        "wallets": len(by_wallet),
        "wallets_by_exchange": dict(sorted(
            pl.DataFrame([{"w": r["wallet"], "e": r["exchange"]} for r in rows]).unique()
            .group_by("e").len().iter_rows())) if rows else {},
        "wallets_with_a_claim": sum(1 for v in by_wallet.values() if v),
        "through_unlabelled": through,
        "all_claims": {k: every[k] for k in ("claims", "right", "wrong")},
        "by_hops": [{"hops": h, "claims": len(g), "right": sum(c["correct"] for c in g)}
                    for h in sorted({c["hops"] for c in claims})
                    for g in [[c for c in claims if c["hops"] == h]]],
        "cases_by_threshold": [_cases_at(by_wallet, t) for t in cfg.grid],
        "current_threshold": current,
        "at_current": {"claims": at, "cases": _cases_at(by_wallet, current)},
    }
    m["notes"] = notes(m)
    return m


def read_validation(out_dir: Path | str, chain: str) -> dict | None:
    path = Path(out_dir) / chain / "validation.json"
    if not path.exists():
        return None
    import json
    return json.loads(path.read_text())


def abstain_info(m: dict) -> dict:
    """validation.json -> the API's AbstainInfo."""
    ind = m["through_unlabelled"]
    t = ind["threshold"]
    bars = [{"threshold": g["threshold"], "claims_answered": g["n_answered"],
             "claims_wrong": g["errors"], "risk": g["risk"],
             "risk_upper_bound": g["risk_upper_bound"], "wallets_named": c["named"],
             "wallets_wrong": c["wrong"], "wallets_abstained": c["abstained"]}
            for g, c in zip(t["grid"], m["cases_by_threshold"])]
    return {"chain": m["chain"], "wallets": m["wallets"], "claims": ind["claims"],
            "current_threshold": m["current_threshold"],
            "measured_threshold": t["threshold"] if t["attainable"] else None,
            "target_risk": t["target_risk"], "delta": t["delta"], "bars": bars,
            "risk_coverage": [{"coverage": p["coverage"], "accuracy": round(1 - p["risk"], 4)}
                              for p in ind["risk_coverage"].get("curve", [])],
            "notes": m["notes"]}


def risk_coverage_svg(m: dict) -> str:
    """Risk against coverage for the claims made through unlabelled wallets: answering the
    most confident claims first, what share of the answers given is wrong. The bars on the
    grid are marked; the one in use is named."""
    from html import escape

    from ..classify.explain import _open
    ind = m["through_unlabelled"]
    curve = ind["risk_coverage"].get("curve", [])
    W, H, x0, y0, w, h = 640, 400, 64, 76, 536, 240
    top = max([0.2] + [p["risk"] for p in curve]) * 1.1
    top = min(1.0, max(0.1, round(top + 0.049, 1)))

    def px(v: float) -> float:
        return x0 + v * w

    def py(v: float) -> float:
        return y0 + (1 - min(v, top) / top) * h

    out = _open(W, H, f"Risk against coverage of the abstain bar on {m['chain']}")
    out += [f'<text class="t" x="{x0}" y="28">What abstaining buys: '
            f'{escape(m["chain"].title())}, {ind["claims"]:,} claims from {m["wallets"]:,} '
            'real wallets</text>',
            f'<text class="s" x="{x0}" y="48">Wrong answers as more claims are answered, most '
            'confident first (derived labels hidden)</text>']
    for i in range(5):
        tick = top * i / 4
        out.append(f'<line class="{"a" if i == 0 else "g"}" x1="{x0}" x2="{x0 + w}" '
                   f'y1="{py(tick):.1f}" y2="{py(tick):.1f}"/>')
        out.append(f'<text class="m" x="{x0 - 8}" y="{py(tick) + 4:.1f}" '
                   f'text-anchor="end">{tick:.0%}</text>')
    for tick in (0, 0.25, 0.5, 0.75, 1):
        out.append(f'<text class="m" x="{px(tick):.1f}" y="{y0 + h + 18}" '
                   f'text-anchor="middle">{tick:.0%}</text>')
    target = ind["threshold"]["target_risk"]
    out += [f'<text class="m" x="{x0 + w}" y="{y0 + h + 36}" text-anchor="end">share of the '
            'claims answered (coverage)</text>',
            f'<text class="m" x="{x0}" y="{y0 - 10}">wrong among the answers (risk)</text>',
            f'<line class="d" x1="{x0}" x2="{x0 + w}" y1="{py(target):.1f}" '
            f'y2="{py(target):.1f}"/>',
            f'<text class="m" x="{x0 + w}" y="{y0 - 10}" text-anchor="end">dashed line: '
            f'{target:.0%} risk</text>']
    if len(curve) > 1:
        out.append('<polyline class="l" points="' + " ".join(
            f'{px(p["coverage"]):.1f},{py(p["risk"]):.1f}' for p in curve) + '"/>')
    n = ind["claims"] or 1
    for g in ind["threshold"]["grid"]:
        if not g["n_answered"]:
            continue
        x, y = px(g["n_answered"] / n), py(g["risk"])
        mine = g["threshold"] == m["current_threshold"]
        out.append(f'<circle class="p" cx="{x:.1f}" cy="{y:.1f}" r="{6 if mine else 4}"><title>'
                   f'Bar {g["threshold"]:.2f}: {g["n_answered"]:,} claims answered, '
                   f'{g["errors"]:,} wrong ({g["risk"]:.1%})</title></circle>')
        if mine:
            out.append(f'<text class="v" x="{x + 10:.1f}" y="{y + 22:.1f}">bar '
                       f'{g["threshold"]:.2f} in use: {g["risk"]:.1%} wrong</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"
