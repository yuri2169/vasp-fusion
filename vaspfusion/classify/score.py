"""Model scores for the derived deposit labels: `artifacts/model_v1/<chain>/scores.csv`.

Each derived address carries its cross-fit score (train.py): the probability from a
model trained on other addresses, its own exchange's included, never on the address
itself. So no label is scored by a model that trained on it.

    label confidence = weight of the label of the exchange wallet it sweeps to
                       x calibrated P(the address is an exchange deposit address)

The first factor says how far the exchange wallet's own label is trusted (0.95 for
a wallet the exchange published, 0.85 for a curated list); it is rule-set, because
nothing here can measure it. The second is the model's. The Venn-Abers range goes
through the same product. `make labels` reads this file and nothing else of the
model, so the label DB builds without the model and without any cache.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import polars as pl

from ..attribute.rules import TIER_WEIGHT
from ..explain import fmt
from .dataset import Run
from .explain import reasons
from .train import Result

COLUMNS = ["address", "chain", "entity", "p", "p_low", "p_high", "confidence",
           "confidence_low", "confidence_high", "scored_by", "reasons", "evidence"]
_FLOATS = ("p", "p_low", "p_high", "confidence", "confidence_low", "confidence_high")
_RULE_CONFIDENCE = re.compile(r"Rule confidence \d\.\d+, not calibrated\.$")


def _evidence(rule_text: str, entity: str, tier: str, row: dict) -> str:
    kept = _RULE_CONFIDENCE.sub("", rule_text).rstrip()
    return (f"{kept} Model: {row['p']:.2f} that this is an exchange deposit address (range "
            f"{row['p_low']:.2f} to {row['p_high']:.2f}), from a model that did not train on "
            f"this address. Label confidence {row['confidence']:.2f} = "
            f"{TIER_WEIGHT[tier]:.2f} for the {entity} wallet's label "
            f"({fmt.tier_words(tier)}) × {row['p']:.2f}.")


def score_labels(df: pl.DataFrame, result: Result, runs: list[Run], top: int = 3) -> list[dict]:
    """One row per derived address that has an out-of-fold score, by address."""
    derived = {}
    for run in runs:
        for f in run.findings:
            if f.status == "derived":
                derived.setdefault(f.address, f)
    oof = result.oof.filter(pl.col("address").is_in(list(derived))).sort("address")
    rows = []
    for fold in sorted(set(oof["fold"].to_list())):
        part = oof.filter(pl.col("fold") == fold)
        features = df.join(part.select("address"), on="address", how="inner").sort("address")
        why = reasons(result.folds[fold], features, top=top)
        for score, row_reasons in zip(part.to_dicts(), why):
            f = derived[score["address"]]
            weight = TIER_WEIGHT[f.target_tier]
            row = {"address": f.address, "chain": f.chain, "entity": f.entity,
                   "p": round(score["p"], 4), "p_low": round(score["low"], 4),
                   "p_high": round(score["high"], 4),
                   "confidence": round(weight * score["p"], 4),
                   "confidence_low": round(weight * score["low"], 4),
                   "confidence_high": round(weight * score["high"], 4),
                   "scored_by": f"cross-fit:{fold}",
                   "reasons": json.dumps(row_reasons, ensure_ascii=False, sort_keys=True)}
            row["evidence"] = _evidence(f.evidence, f.entity, f.target_tier, row)
            rows.append(row)
    rows.sort(key=lambda r: r["address"])
    return rows


def write_scores(path: Path | str, rows: list[dict]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(COLUMNS)
        for r in sorted(rows, key=lambda r: (r["chain"], r["address"])):
            w.writerow([r[c] for c in COLUMNS])
    return path


def read_scores(path: Path | str) -> dict[tuple[str, str], dict]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        rows = [{**r, **{k: float(r[k]) for k in _FLOATS}} for r in csv.DictReader(fh)]
    return {(r["address"], r["chain"]): r for r in rows}
