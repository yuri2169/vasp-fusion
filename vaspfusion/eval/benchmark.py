"""Attribution measured on every chain, beside a naive baseline.

The question: a wallet paid an exchange; with the label that says so taken away, does
the tool still name the exchange, and how often is the name wrong?

PROTOCOL (fixed before any wallet was sampled; `protocol()` writes it into every file).

Sampling, every chain except Tron. The chain's exchanges are ranked by how many labelled
addresses they have there and the top `top_exchanges` are taken. Each one's labelled
addresses are shuffled with the seed and the first `max_addresses` are probed: one
listing of the transfers INTO the address per sampled asset. A sender is eligible when
it sent at least `min_amount`, is a plain address, has no label of any kind and was not
taken already. Senders are taken round-robin over the probed addresses (one from each,
then a second from each, ...) up to the exchange's quota. A wallet is traced from the
time of its sampled payment.

Hiding. Every label in a VASP category on an address the wallet paid directly is
hidden, and the label of the sampled address is hidden whether or not the listing shows
it. Nothing two or more hops out is hidden. So no answer can rest on a label one hop
from the wallet: the exchange has to be found again through an unlabelled wallet. The
known answer is the sampled exchange plus the owner of every hidden label.

Tron is the existing run (artifacts/abstain_v1/tron/claims.csv, 280 wallets, not
re-picked). There only the derived labels were hidden, and a claim one hop away, which
rests on a label that was not hidden, is kept out of every figure.

Our method: the pipeline's own answer (the nearest exchange at or above the bar).
Baseline: the nearest labelled exchange the same trace reached, whatever its
confidence. It never abstains when anything was reached. Both read the same trace, so
the comparison is of the decision rule alone.

Seconds are measured when a wallet is first traced from the network and are carried
through later replays, so a replay gives the same file byte for byte.
"""
from __future__ import annotations

import csv
import random
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import median

from ..attribute.rules import RuleConfig, attribute
from ..chains.base import ProviderError
from ..cluster import cluster_labels
from ..labels.normalize import VASP_CATEGORIES
from ..trace import TraceConfig, trace

SEED = 26182
VERSION = "benchmark_v1"
CHAINS = ("tron", "ethereum", "bitcoin", "bsc", "polygon", "solana")
QUOTA = {"ethereum": 30}                    # wallets per exchange; DEFAULT_QUOTA elsewhere
DEFAULT_QUOTA = 12
SAMPLED_ASSETS = {"bitcoin": ("BTC",)}      # elsewhere the two stablecoins
STABLE = ("USDT", "USDC")
MIN_AMOUNT = {"BTC": Decimal("0.001")}      # elsewhere 10 units of the stablecoin
BINS = (0.0, 0.3, 0.6, 0.75, 0.9, 1.0)
MIN_FOR_CALIBRATION = 20
SAMPLE_COLUMNS = ["exchange", "paid", "kind", "tier", "wallet", "tx", "since", "asset", "amount"]
COLUMNS = ["wallet", "exchange", "paid", "since", "known", "hidden", "asset", "outcome",
           "named", "right", "hops", "confidence", "share", "base_named", "base_right",
           "base_hops", "base_confidence", "candidates", "stopped", "error", "seconds",
           "requests"]


@dataclass(frozen=True)
class BenchmarkConfig:
    seed: int = SEED
    top_exchanges: int = 8
    max_addresses: int = 40
    listing_limit: int = 100
    trace: TraceConfig = TraceConfig(max_hops=3, inbound_hops=0)
    rules: RuleConfig = RuleConfig()

    def quota(self, chain: str) -> int:
        return QUOTA.get(chain, DEFAULT_QUOTA)


def sampled_assets(chain: str) -> tuple[str, ...]:
    return SAMPLED_ASSETS.get(chain, STABLE)


def min_amount(asset: str) -> Decimal:
    return MIN_AMOUNT.get(asset, Decimal(10))


def protocol(chain: str, cfg: BenchmarkConfig = BenchmarkConfig()) -> dict:
    if chain == "tron":
        return {
            "wallets": "the 280 wallets of artifacts/abstain_v1/tron (40 per exchange, a "
                       "seeded sample of the deposit model's customers); not re-picked",
            "hidden": "every derived label (5,497 deposit addresses). Labels from other "
                      "sources were not hidden; a claim one hop away rests on one of them "
                      "and is kept out of every figure",
            "known_answer": "the exchange whose derived deposit address the wallet paid, "
                            "plus the exchanges it paid directly by the full label store",
            "seed": cfg.seed, "bar": cfg.rules.attribute_min, "max_hops": cfg.trace.max_hops}
    assets = sampled_assets(chain)
    return {
        "exchanges": f"the {cfg.top_exchanges} exchanges with the most labelled addresses "
                     "on the chain (category exchange, not derived; ties by name)",
        "quota_per_exchange": cfg.quota(chain),
        "addresses_probed": f"each exchange's labelled addresses, shuffled with the seed, "
                            f"the first {cfg.max_addresses}",
        "listing": f"transfers into the address, {' and '.join(assets)}, one listing of "
                   f"{cfg.listing_limit} per asset ("
                   + ("the newest; the adapter offers nothing else" if chain == "bitcoin"
                      else "the oldest") + ")",
        "eligible_sender": f"sent at least {', '.join(f'{min_amount(a)} {a}' for a in assets)}"
                           "; a plain address; no label of any kind; not taken already",
        "choice": "round-robin over the probed addresses, senders of one address in a "
                  "seeded order; no top-up from another exchange when one falls short",
        "traced_from": "the time of the sampled payment",
        "hidden": "every label in a VASP category (exchange, custodial wallet, swap "
                  "service) on an address the wallet paid directly since then, and the "
                  "label of the sampled address in any case. Nothing two or more hops out",
        "known_answer": "the sampled exchange, plus the owner of every hidden label",
        "seed": cfg.seed, "bar": cfg.rules.attribute_min, "max_hops": cfg.trace.max_hops,
        "wallet_budget": cfg.trace.max_nodes, "transfers_per_listing": cfg.trace.fetch_limit}


# ------------------------------------------------------------------ sampling
def exchange_labels(store, chain: str) -> list:
    """The chain's own exchange labels that are not derived."""
    return [lab for lab in store.non_derived_exchanges(chain)]


def exchanges_for(labels: list, cfg: BenchmarkConfig = BenchmarkConfig()
                  ) -> list[tuple[str, list]]:
    """[(exchange, its labels)] for the exchanges with the most labelled addresses."""
    by: dict[str, list] = {}
    for lab in labels:
        by.setdefault(lab.entity, []).append(lab)
    ranked = sorted(by, key=lambda e: (-len(by[e]), e))[:cfg.top_exchanges]
    return [(e, sorted(by[e], key=lambda lab: lab.address)) for e in ranked]


def _plain(address: str) -> bool:
    return bool(address) and ":" not in address and set(address.lower()) - set("0x")


def sample_chain(chain: str, labels: list, provider, lookup,
                 cfg: BenchmarkConfig = BenchmarkConfig(), progress=None
                 ) -> tuple[list[dict], dict]:
    """(the sampled wallets, a report of what was probed). `lookup` is the full label
    store. Depends only on the labels, the seed and the listings read."""
    picked: list[dict] = []
    taken: set[str] = set()
    report = {"exchanges": [], "listings_unreadable": 0}
    for exchange, labs in exchanges_for(labels, cfg):
        order = [lab.address for lab in labs]
        random.Random(f"{cfg.seed}:benchmark:{chain}:{exchange}").shuffle(order)
        by_addr = {lab.address: lab for lab in labs}
        queues: list[tuple[str, list[tuple[str, object]]]] = []
        for paid in order[:cfg.max_addresses]:
            first: dict[str, object] = {}        # sender -> its earliest eligible transfer
            for asset in sampled_assets(chain):
                try:
                    rows = provider.transfers(paid, "in", since=None, limit=cfg.listing_limit,
                                              asset=asset)
                except ProviderError:
                    report["listings_unreadable"] += 1
                    continue
                for t in rows:
                    if t.to_addr != paid or t.from_addr == paid or not _plain(t.from_addr) \
                            or t.amount < min_amount(asset):
                        continue
                    was = first.get(t.from_addr)
                    if was is None or (t.block_time, t.tx_hash) < (was.block_time, was.tx_hash):
                        first[t.from_addr] = t
            labelled = lookup.lookup_many([(s, chain) for s in sorted(first)])
            senders = sorted(s for s in first if (s, chain) not in labelled)
            random.Random(f"{cfg.seed}:benchmark:{chain}:{paid}").shuffle(senders)
            queues.append((paid, [(s, first[s]) for s in senders]))
            if progress:
                progress("probed", len(queues), min(len(order), cfg.max_addresses))
        quota, got, depth = cfg.quota(chain), 0, 0
        while got < quota and any(len(q) > depth for _, q in queues):
            for paid, q in queues:
                if got >= quota:
                    break
                if len(q) > depth and q[depth][0] not in taken:
                    wallet, t = q[depth]
                    taken.add(wallet)
                    lab = by_addr[paid]
                    picked.append({"exchange": exchange, "paid": paid, "kind": lab.kind,
                                   "tier": lab.tier, "wallet": wallet, "tx": t.tx_hash,
                                   "since": t.block_time.isoformat(), "asset": t.asset,
                                   "amount": str(t.amount)})
                    got += 1
            depth += 1
        report["exchanges"].append({
            "exchange": exchange, "labelled_addresses": len(labs),
            "addresses_probed": len(queues),
            "addresses_with_an_eligible_sender": sum(1 for _, q in queues if q),
            "eligible_senders": sum(len(q) for _, q in queues), "wallets": got,
            "quota": quota})
    return picked, report


# ------------------------------------------------------------------ one wallet
class HiddenLabels:
    """A label lookup that does not know the labels of the given addresses."""

    def __init__(self, labels, hidden: set[str]):
        self.labels, self.hidden = labels, hidden

    def lookup_many(self, pairs):
        return {k: v for k, v in self.labels.lookup_many(pairs).items()
                if k[0] not in self.hidden}


def hidden_for(wallet: str, paid: str, exchange: str, since: datetime | None, chain: str,
               provider, labels, cfg: BenchmarkConfig) -> tuple[set[str], set[str]]:
    """(addresses whose label is hidden, the known answer). Reads the listings the trace
    reads first: the wallet's outgoing transfers of each traceable asset."""
    direct = {paid}
    for asset in provider.traceable_assets:
        for t in provider.transfers(wallet, "out", since=since, limit=cfg.trace.fetch_limit,
                                    asset=asset):
            if t.from_addr == wallet and _plain(t.to_addr):
                direct.add(t.to_addr)
    found = labels.lookup_many([(a, chain) for a in sorted(direct)])
    vasp = {a: lab for (a, _), lab in found.items() if lab.category in VASP_CATEGORIES}
    return set(vasp) | {paid}, {exchange} | {lab.entity for lab in vasp.values()}


def _stopped(tr) -> str:
    total = sum(tr.stopped.values(), Decimal(0))
    if not total:
        return ""
    parts = sorted(tr.stopped.items(), key=lambda kv: (-kv[1], kv[0]))
    return "|".join(f"{k}={float(v / total):.2f}" for k, v in parts if v > 0)


def trace_wallet(item: dict, chain: str, provider, labels,
                 cfg: BenchmarkConfig = BenchmarkConfig(), fetcher=None,
                 clock=time.monotonic) -> dict:
    """One row: what the pipeline and the baseline say about one sampled wallet with the
    labels one hop away hidden."""
    wallet, since = item["wallet"], datetime.fromisoformat(item["since"])
    row = {c: "" for c in COLUMNS}
    row.update(wallet=wallet, exchange=item["exchange"], paid=item["paid"], since=item["since"])
    before = dict(fetcher.stats) if fetcher is not None else None
    start = clock()
    try:
        hidden, known = hidden_for(wallet, item["paid"], item["exchange"], since, chain,
                                   provider, labels, cfg)
        how = TraceConfig(**{**cfg.trace.__dict__, "since": since})
        view = cluster_labels(chain, HiddenLabels(labels, hidden), provider)
        tr = trace(wallet, chain, provider, view, how)
        att = attribute(tr, cfg.rules)
    except ProviderError as e:
        row.update(known=item["exchange"], error=str(e)[:200])
    else:
        out = [c for c in att.candidates if c.direction == "outbound"]
        row.update(known="|".join(sorted(known)), hidden=len(hidden), asset=tr.asset or "",
                   outcome=att.outcome, named="", candidates=len(out), stopped=_stopped(tr))
        if att.top is not None:
            row.update(named=att.top.vasp, right=int(att.top.vasp in known),
                       hops=att.top.hops_min, confidence=att.top.confidence,
                       share=round(float(att.top.share), 4))
        if out:
            b = min(out, key=lambda c: c.proximity_rank)
            row.update(base_named=b.vasp, base_right=int(b.vasp in known),
                       base_hops=b.hops_min, base_confidence=b.confidence)
    row["seconds"] = round(clock() - start, 2)
    if before is not None:
        row["requests"] = sum(fetcher.stats[k] - before[k] for k in ("live", "hits"))
        row["_live"] = fetcher.stats["live"] - before["live"]
    return row


def collect(sample: list[dict], chain: str, provider, labels,
            cfg: BenchmarkConfig = BenchmarkConfig(), fetcher=None, earlier: list[dict] = (),
            progress=None, save=None) -> list[dict]:
    """Every sampled wallet's row, in wallet order. `earlier`: the rows of a previous
    run; a wallet that needed nothing from the network this time keeps the seconds it
    was first traced in."""
    was = {r["wallet"]: r for r in earlier}
    rows = []
    for i, item in enumerate(sorted(sample, key=lambda s: s["wallet"]), 1):
        row = trace_wallet(item, chain, provider, labels, cfg, fetcher)
        live = row.pop("_live", None)
        old = was.get(row["wallet"])
        if old is not None and not live and old.get("seconds") not in ("", None):
            row["seconds"] = old["seconds"]
        rows.append(row)
        if progress:
            progress("wallets", i, len(sample))
        if save and i % 10 == 0:
            save(rows)
    return rows


# ------------------------------------------------------------------ the CSVs
def write_csv(path: Path | str, rows: list[dict], columns: list[str]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(columns)
        for r in rows:
            w.writerow([r.get(c, "") for c in columns])
    return path


def read_csv(path: Path | str) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in ("right", "hops", "base_right", "base_hops", "hidden", "candidates",
                  "requests"):
            if r.get(k, "") != "":
                r[k] = int(r[k])
        for k in ("confidence", "share", "base_confidence", "seconds"):
            if r.get(k, "") != "":
                r[k] = float(r[k])
    return rows


# ------------------------------------------------------------------ Tron, from B7's claims
def tron_rows(claims: list[dict], bar: float) -> list[dict]:
    """The Tron run in this module's row shape. Only claims made through an unlabelled
    wallet count (B7): ours is the nearest one at or above the bar, the baseline the
    nearest one."""
    by: dict[str, list[dict]] = {}
    meta: dict[str, dict] = {}
    for c in claims:
        by.setdefault(c["wallet"], [])
        meta[c["wallet"]] = c
        if c["vasp"] and not c["direct"]:
            by[c["wallet"]].append(c)
    rows = []
    for wallet in sorted(by):
        mine = by[wallet]
        row = {c: "" for c in COLUMNS}
        row.update(wallet=wallet, exchange=meta[wallet]["exchange"],
                   known=meta[wallet]["known"], candidates=len(mine))
        clearing = [c for c in mine if c["confidence"] >= bar]
        if clearing:
            top = min(clearing, key=lambda c: c["rank"])
            row.update(named=top["vasp"], right=top["correct"], hops=top["hops"],
                       confidence=top["confidence"], share=top["share"])
        if mine:
            b = min(mine, key=lambda c: c["rank"])
            row.update(base_named=b["vasp"], base_right=b["correct"], base_hops=b["hops"],
                       base_confidence=b["confidence"])
        rows.append(row)
    return rows


# ------------------------------------------------------------------ the figures
def upper_bound(wrong: int, named: int, level: float = 0.05) -> float | None:
    """One-sided Clopper-Pearson upper bound on the error rate among the named."""
    from scipy.stats import beta
    if not named:
        return None
    return 1.0 if wrong >= named else round(float(beta.ppf(1 - level, wrong + 1,
                                                          named - wrong)), 4)


def _method(rows: list[dict], prefix: str) -> dict:
    named = [r for r in rows if r[prefix + "named"] != ""]
    wrong = sum(1 for r in named if not r[prefix + "right"])
    hops = sorted({r[prefix + "hops"] for r in named})
    return {"named": len(named), "wrong": wrong, "right": len(named) - wrong,
            "not_named": len(rows) - len(named),
            "error": round(wrong / len(named), 4) if named else None,
            "error_upper_95": upper_bound(wrong, len(named)),
            "by_hops": [{"hops": h, "named": len(g), "wrong": sum(1 for r in g
                                                                  if not r[prefix + "right"])}
                        for h in hops
                        for g in [[r for r in named if r[prefix + "hops"] == h]]]}


def calibration(rows: list[dict]) -> dict:
    """Stated confidence against observed correctness, over the wallets where the trace
    reached an exchange at all: the confidence and correctness of the nearest one."""
    given = [(float(r["base_confidence"]), int(r["base_right"])) for r in rows
             if r["base_named"] != ""]
    out = {"wallets_with_a_confidence": len(given)}
    if len(given) < MIN_FOR_CALIBRATION:
        return {**out, "available": False,
                "note": f"Too few to say: fewer than {MIN_FOR_CALIBRATION} wallets were "
                        "given a confidence."}
    bins = []
    for lo, hi in zip(BINS, BINS[1:]):
        g = [(c, ok) for c, ok in given if lo <= c < hi or (hi == BINS[-1] and c == hi)]
        bins.append({"from": lo, "to": hi, "wallets": len(g),
                     "stated": round(sum(c for c, _ in g) / len(g), 4) if g else None,
                     "observed": round(sum(ok for _, ok in g) / len(g), 4) if g else None})
    brier = sum((c - ok) ** 2 for c, ok in given) / len(given)
    base = sum(ok for _, ok in given) / len(given)
    filled = [b for b in bins if b["wallets"] >= 5]
    rising = all(a["observed"] <= b["observed"] for a, b in zip(filled, filled[1:]))
    return {**out, "available": True, "bins": bins, "brier": round(brier, 4),
            "share_right": round(base, 4),
            # what a constant confidence equal to the share right would score
            "brier_of_constant": round(base * (1 - base), 4),
            "informative": bool(len(filled) >= 2 and rising
                                and brier < base * (1 - base))}


def _stop_reasons(rows: list[dict]) -> dict:
    """For the wallets not named: the main reason the traced money stopped."""
    out: dict[str, int] = {}
    for r in rows:
        if r["named"] != "":
            continue
        why = "provider_error" if r.get("error") else \
            (r["stopped"].split("|")[0].split("=")[0] if r.get("stopped") else "nothing_sent")
        out[why] = out.get(why, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def measure(rows: list[dict], chain: str, cfg: BenchmarkConfig = BenchmarkConfig(),
            sample_report: dict | None = None, collected: dict | None = None) -> dict:
    """wallets.csv -> validation.json."""
    read = [r for r in rows if not r.get("error")]
    secs = [float(r["seconds"]) for r in read if r.get("seconds") not in ("", None)]
    reqs = [int(r["requests"]) for r in read if r.get("requests") not in ("", None)]
    by_exchange: dict[str, dict] = {}
    for r in read:
        e = by_exchange.setdefault(r["exchange"], {"wallets": 0, "named": 0, "wrong": 0})
        e["wallets"] += 1
        if r["named"] != "":
            e["named"] += 1
            e["wrong"] += int(not r["right"])
    m = {"version": VERSION, "chain": chain, "seed": cfg.seed, "bar": cfg.rules.attribute_min,
         "protocol": protocol(chain, cfg),
         "wallets_sampled": len(rows), "wallets": len(read),
         "could_not_be_read": len(rows) - len(read),
         "exchanges": len(by_exchange), "by_exchange": dict(sorted(by_exchange.items())),
         "ours": _method(read, ""), "baseline": _method(read, "base_"),
         "not_named_because": _stop_reasons(read),
         "median_seconds": round(median(secs), 2) if secs else None,
         "median_requests": int(median(reqs)) if reqs else None,
         "calibration": calibration(read)}
    if sample_report is not None:
        m["sampling"] = sample_report
    if collected is not None:
        m["collected"] = collected
    return m


def summarise(per_chain: dict[str, dict]) -> dict:
    """validation.json of each chain -> summary.json (the table)."""
    table = []
    for chain in CHAINS:
        m = per_chain.get(chain)
        if m is None:
            table.append({"chain": chain, "measured": False})
            continue
        o, b = m["ours"], m["baseline"]
        table.append({
            "chain": chain, "measured": True, "wallets": m["wallets"],
            "exchanges": m["exchanges"], "named": o["named"], "wrong": o["wrong"],
            "error": o["error"], "error_upper_95": o["error_upper_95"],
            "not_named": o["not_named"], "by_hops": o["by_hops"],
            "baseline_named": b["named"], "baseline_wrong": b["wrong"],
            "baseline_error": b["error"], "baseline_error_upper_95": b["error_upper_95"],
            "median_seconds": m["median_seconds"], "median_requests": m["median_requests"],
            "calibration_brier": m["calibration"].get("brier"),
            "confidence_informative": m["calibration"].get("informative"),
            "hidden": m["protocol"]["hidden"]})
    return {"version": VERSION, "seed": SEED, "bar": RuleConfig().attribute_min,
            "chains": table, "notes": NOTES}


NOTES = [
    "Each wallet is a real wallet that paid a labelled exchange address. The labels one "
    "hop from it were hidden and it was traced again; a name is right when it is the "
    "exchange the hidden labels belong to.",
    "Named, wrong and the error rate are over wallets. The upper bound is one-sided "
    "Clopper-Pearson at 95% on the error among the wallets named, for the one bar in use "
    "(0.60), which was fixed before the measurement.",
    "Baseline: the nearest labelled exchange the same trace reached, whatever its "
    "confidence. It shares the tracer with our method, so the difference between the two "
    "is the decision to abstain and nothing else.",
    "Tron is the earlier run: only the derived deposit labels were hidden there, and the "
    "wallets were picked from the deposit model's customers. On the other chains the "
    "labels hidden are source labels and the wallets come from the inbound transfers of "
    "labelled exchange addresses, so the Tron row is not like for like with the others.",
    "Every wallet here paid an exchange. Nothing measures wallets that never did.",
    "A sender into an exchange's hot wallet can be the exchange's own unlabelled deposit "
    "address, or a contract, and is counted as a wallet like any other.",
]
