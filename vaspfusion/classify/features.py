"""What an address does, as numbers: the inputs of the deposit-address model (B6).

One listing of an address's transfers and one listing of who covered its fees go
in; a row of features comes out. `FEATURES` read behaviour only. They never look
at a label, so the model can recognise a deposit address of an exchange we hold
no label for. `LABEL_FEATURES` read the labelled exchange wallets the address
touches. On Tron the positives were picked by exactly that (B4's rules), so those
two are kept out of the shipped model and reported as an ablation; `hidden`
removes an exchange's labels the way a fold that holds that exchange out must.

Pairing is B4's (discover/rules.py): per asset, each outflow is matched to the
deposits that arrived before it, newest first. Amounts are only ever compared
within one asset; across assets the shares are weighted by transfer counts, so
no price feed is needed.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from statistics import median, pstdev

from ..chains.base import GasEvent, Transfer
from ..discover.rules import DiscoverConfig, gas_rule, is_seed

NAN = float("nan")
ZERO = Decimal(0)

FEATURES = ["forward_ratio", "top_recipient_share", "dwell_median_s", "left_share",
            "n_senders", "n_recipients", "n_in", "n_out", "out_per_in", "sweep_gap_cv",
            "stable_share", "gas_outside_share", "gas_payers", "age_days"]
LABEL_FEATURES = ["to_exchange_share", "gas_from_exchange_share"]


def _usable(address: str, rows: list[Transfer], dust: Decimal) -> list[Transfer]:
    kept = [t for t in rows
            if address in (t.from_addr, t.to_addr) and t.from_addr != t.to_addr
            and (t.amount_usd >= dust if t.amount_usd is not None else t.amount > 0)]
    # the same total order as the sweep rule: a deposit and an outflow in one second,
    # the deposit came first
    kept.sort(key=lambda t: (t.block_time, t.from_addr == address, t.tx_hash, t.to_addr,
                             t.from_addr, t.asset, t.amount))
    return kept


def _pair(address: str, rows: list[Transfer], top: str | None) -> dict:
    """One asset's rows: what arrived before the last outflow, how much of it left to
    `top`, what is still there, and how long each moved part waited."""
    outs = [i for i, t in enumerate(rows) if t.from_addr == address]
    deposits = [t for t in rows if t.to_addr == address]
    last_out = outs[-1] if outs else -1
    before = [t for t in rows[:last_out + 1] if t.to_addr == address]
    unspent: list[list] = []                      # [amount left, arrival time], oldest first
    to_top, waits = ZERO, []
    for t in rows[:last_out + 1]:
        if t.to_addr == address:
            unspent.append([t.amount, t.block_time])
            continue
        left = t.amount
        while left > 0 and unspent:               # newest deposit first
            part = min(left, unspent[-1][0])
            waits.append((t.block_time - unspent[-1][1]).total_seconds())
            if t.to_addr == top:
                to_top += part
            unspent[-1][0] -= part
            left -= part
            if unspent[-1][0] == 0:
                unspent.pop()
    total_in = sum((t.amount for t in deposits), ZERO)
    still = sum((u[0] for u in unspent), ZERO) \
        + sum((t.amount for t in rows[last_out + 1:] if t.to_addr == address), ZERO)
    received = sum((t.amount for t in before), ZERO)
    return {"n_before": len(before), "forward": float(to_top / received) if received else NAN,
            "n_deposits": len(deposits), "left": float(still / total_in) if total_in else NAN,
            "waits": waits}


def _weighted(parts: list[tuple[int, float]]) -> float:
    weight = sum(n for n, _ in parts)
    return sum(n * v for n, v in parts) / weight if weight else NAN


def address_features(address: str, rows: list[Transfer], events: list[GasEvent],
                     labels: dict | None = None, hidden: tuple[str, ...] = (),
                     cfg: DiscoverConfig = DiscoverConfig()) -> dict | None:
    """The feature row of `address`, plus `first_ts`, `n_rows` and `label_entity`.
    None when the listing holds no usable transfer. `labels` (address -> Label) is
    only read for `LABEL_FEATURES`; labels of the exchanges in `hidden` are not seen."""
    rows = _usable(address, list(rows), cfg.dust)
    if not rows:
        return None
    seen = {a: lab for a, lab in (labels or {}).items()
            if is_seed(lab) and lab.entity not in hidden}
    ins = [t for t in rows if t.to_addr == address]
    outs = [t for t in rows if t.from_addr == address]
    to_count = Counter(t.to_addr for t in outs)
    top = min(to_count, key=lambda a: (-to_count[a], a)) if outs else None

    by_asset: dict[str, list[Transfer]] = defaultdict(list)
    for t in rows:
        by_asset[t.asset].append(t)
    paired = [_pair(address, by_asset[a], top) for a in sorted(by_asset)]
    waits = [w for p in paired for w in p["waits"]]
    times = [t.block_time for t in outs]
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    mean_gap = sum(gaps) / len(gaps) if gaps else 0.0

    gas = gas_rule(address, outs, list(events), seen, entity="", cfg=cfg)
    near: Counter = Counter(seen[t.to_addr].entity for t in outs if t.to_addr in seen)
    paid_by: Counter = Counter()
    for payer, entity in gas.seed_payers.items():
        paid_by[entity] += gas.payers[payer]
    touched = near + paid_by
    return {
        "forward_ratio": _weighted([(p["n_before"], p["forward"]) for p in paired
                                    if p["n_before"]]),
        "top_recipient_share": to_count[top] / len(outs) if outs else NAN,
        "dwell_median_s": float(median(waits)) if waits else NAN,
        "left_share": _weighted([(p["n_deposits"], p["left"]) for p in paired
                                 if p["n_deposits"]]),
        "n_senders": len({t.from_addr for t in ins}),
        "n_recipients": len(to_count),
        "n_in": len(ins),
        "n_out": len(outs),
        "out_per_in": len(outs) / len(ins) if ins else NAN,
        "sweep_gap_cv": pstdev(gaps) / mean_gap if len(gaps) >= 2 and mean_gap > 0 else NAN,
        "stable_share": sum(1 for t in rows if t.amount_usd is not None) / len(rows),
        "gas_outside_share": gas.n_paid / len(outs) if outs else NAN,
        "gas_payers": len(gas.payers),
        "age_days": (rows[-1].block_time - rows[0].block_time).total_seconds() / 86400,
        "to_exchange_share": sum(near.values()) / len(outs) if outs else NAN,
        "gas_from_exchange_share": min(1.0, sum(paid_by.values()) / len(outs)) if outs else NAN,
        "label_entity": min(touched, key=lambda e: (-touched[e], e)) if touched else None,
        "first_ts": rows[0].block_time,
        "n_rows": len(rows),
    }
