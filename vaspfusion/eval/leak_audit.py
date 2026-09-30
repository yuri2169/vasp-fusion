"""Apply VASP-FUSION's leak test to someone else's synthetic AML data.

Our generator is gated on a leak test: a model trained only on fields with no
constructed path to the label must score at the base rate. Published synthetic
AML datasets report no such check. Three generic probes need no knowledge of the
generator, plus whatever fields its paper declares label-independent:
  * identifier order  - IDs are assigned arbitrarily; if their rank predicts
                        laundering, IDs were assigned in label order.
  * row position      - informative only: legitimate if laundering clusters in time.
  * timestamp minute/second - a generator that draws clock times independently
                        of the label must not let them predict it.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import yaml

from ..detect.supervised import SupervisedDetector
from . import metrics as M

GATE = 1.30


def audit(frame: pl.DataFrame, label: str, id_fields: list[str], timestamp: dict | None,
          declared_independent: list[str], seed: int = 0) -> dict:
    y = frame.get_column(label).cast(pl.Int8).to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(y))
    cut = int(0.7 * len(y))
    tr, te = idx[:cut], idx[cut:]
    base = float(y[te].mean())

    probes: dict[str, np.ndarray] = {"row_position": np.arange(len(y), dtype=np.float32)}
    for f in id_fields:
        probes[f"{f}__rank"] = frame.get_column(f).rank("dense").cast(pl.Float32).to_numpy()
    if timestamp:
        ts = frame.get_column(timestamp["column"]).str.strptime(
            pl.Datetime, timestamp["format"], strict=False)
        probes["timestamp_minute"] = ts.dt.minute().cast(pl.Float32).to_numpy()
        probes["timestamp_second"] = ts.dt.second().cast(pl.Float32).to_numpy()
    for f in declared_independent:
        col = frame.get_column(f)
        probes[f] = (col.cast(pl.Float32, strict=False) if col.dtype.is_numeric()
                     else col.rank("dense").cast(pl.Float32)).to_numpy()

    fields = {}
    for name, x in probes.items():
        X = np.nan_to_num(np.asarray(x, dtype=np.float32).reshape(-1, 1), nan=-1.0)
        m = SupervisedDetector(seed=seed, backend="sklearn_histgb").fit(
            X[tr], y[tr], [name], n_estimators=200)
        pr = M.pr_auc(y[te], m.predict_proba(X[te]))
        fields[name] = {"pr_auc": round(pr, 4), "lift": round(pr / max(base, 1e-9), 3),
                        "tier": "informative" if name == "row_position" else "strict"}
    return {"n": int(len(y)), "base_rate": round(base, 6), "fields": fields,
            "strict_over_gate": sorted(k for k, v in fields.items()
                                       if v["tier"] == "strict" and v["lift"] >= GATE),
            "gate": GATE}


def run_leak_audit(spec_path: Path, dataset: str, out: Path) -> dict:
    spec = yaml.safe_load(Path(spec_path).read_text())[dataset]
    frame = pl.read_csv(spec["path"], n_rows=spec.get("max_rows"), infer_schema_length=10000)
    res = {"dataset": dataset, "citation": spec.get("citation"),
           **audit(frame, spec["label"], spec.get("id_fields", []), spec.get("timestamp"),
                   spec.get("declared_independent", []))}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2))
    return res
