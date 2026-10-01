"""Model scores for the derived deposit labels: `artifacts/model_v1/<chain>/scores.csv`.

Each derived address carries its cross-fit score (train.py): the probability from a
model trained on other addresses, its own exchange's included, never on the address
itself. So no label is scored by a model that trained on it.

How the score becomes a label's confidence (`fuse`):

    model value = weight of the label of the exchange wallet it sweeps to
                  x calibrated P(an address behaving like this is a deposit address)

* The model confirms the label when that value is at least the confidence the
  discovery rules gave it. The label then carries the model value and its
  Venn-Abers range (the low end is never below the rules' confidence).
* Otherwise the rules' confidence is kept, with no range, and the evidence says
  why: the model agrees but adds nothing, or it does not recognise the behaviour.
  The model reads behaviour only. It cannot see the
  one thing the rules saw, the sweep into a labelled exchange wallet, so its doubt
  about an unusual address is reported and never multiplied in.

The weight of the exchange wallet's label (0.95 published by the exchange, 0.85
curated list) is rule-set: nothing here can measure it. `make labels` reads this
file and nothing else of the model, so the label DB builds without the model and
without any cache.
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

COLUMNS = ["address", "chain", "entity", "p", "p_low", "p_high", "rule_confidence", "basis",
           "confidence", "confidence_low", "confidence_high", "scored_by", "model",
           "evidence"]
_FLOATS = ("p", "p_low", "p_high", "rule_confidence", "confidence", "confidence_low",
           "confidence_high")
_RULE_CONFIDENCE = re.compile(r"Rule confidence \d\.\d+, not calibrated\.$")


def fuse(rule_confidence: float, weight: float, p: float, low: float, high: float) -> dict:
    """The label's confidence from the rules' confidence and the model's probability."""
    value = round(weight * p, 4)
    if value < rule_confidence:
        return {"basis": "rule", "confidence": rule_confidence, "confidence_low": None,
                "confidence_high": None}
    return {"basis": "model", "confidence": value,
            "confidence_low": max(rule_confidence, round(weight * low, 4)),
            "confidence_high": round(weight * high, 4)}


def evidence_text(rule_text: str, entity: str, tier: str, row: dict) -> str:
    """The rules' paragraph, then what the model said and which confidence the label has."""
    text = (f"{_RULE_CONFIDENCE.sub('', rule_text).rstrip()} Model: {fmt.prob(row['p'])} "
            "that an address behaving like this is an exchange deposit address "
            f"({fmt.prob_range(row['p_low'], row['p_high'])}), from a model that did not train "
            "on this address. ")
    if row["basis"] == "model":
        return text + (f"Label confidence {row['confidence']:.2f} = {TIER_WEIGHT[tier]:.2f} for "
                       f"the {entity} wallet's label ({fmt.tier_words(tier)}) × the model's "
                       "probability.")
    kept = f"the rule confidence {row['confidence']:.2f} is kept (hand-set, not calibrated)."
    if row["p"] >= 0.5:
        return text + (f"The model agrees, but {TIER_WEIGHT[tier]:.2f} × {fmt.prob(row['p'])} "
                       f"is no more than the rules gave, so {kept}")
    return text + ("The model reads behaviour only and does not recognise this one; it cannot "
                   f"see the sweep into the labelled exchange wallet, so {kept}")


def label_findings(runs: list[Run]) -> dict[str, object]:
    """address -> the discovery finding its label is built from. An address two runs
    derived keeps the more confident finding, as the label loader does (labels/load.py)."""
    best: dict[str, object] = {}
    for run in runs:
        for f in run.findings:
            if f.status != "derived":
                continue
            old = best.get(f.address)
            if old is None or (-f.confidence, f.evidence) < (-old.confidence, old.evidence):
                best[f.address] = f
    return best


def score_labels(df: pl.DataFrame, result: Result, runs: list[Run], top: int = 3) -> list[dict]:
    """One row per derived address that has a cross-fit score, by address."""
    derived = label_findings(runs)
    oof = result.oof.filter(pl.col("address").is_in(list(derived))).sort("address")
    rows = []
    for fold in sorted(set(oof["fold"].to_list())):
        part = oof.filter(pl.col("fold") == fold)
        features = df.join(part.select("address"), on="address", how="inner").sort("address")
        why = reasons(result.folds[fold], features, top=top)
        for score, row_reasons in zip(part.to_dicts(), why):
            f = derived[score["address"]]
            row = {"address": f.address, "chain": f.chain, "entity": f.entity,
                   "p": round(score["p"], 4), "p_low": round(score["low"], 4),
                   "p_high": round(score["high"], 4), "rule_confidence": f.confidence,
                   "scored_by": f"cross-fit:{fold}"}
            row |= fuse(f.confidence, TIER_WEIGHT[f.target_tier], row["p"], row["p_low"],
                        row["p_high"])
            row["model"] = json.dumps(
                {"p": row["p"], "low": row["p_low"], "high": row["p_high"],
                 "basis": row["basis"], "scored_by": row["scored_by"], "reasons": row_reasons},
                ensure_ascii=False, sort_keys=True)
            row["evidence"] = evidence_text(f.evidence, f.entity, f.target_tier, row)
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
            w.writerow(["" if r[c] is None else r[c] for c in COLUMNS])
    return path


def read_scores(path: Path | str) -> dict[tuple[str, str], dict]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        rows = [{**r, **{k: float(r[k]) if r[k] != "" else None for k in _FLOATS}}
                for r in csv.DictReader(fh)]
    return {(r["address"], r["chain"]): r for r in rows}
