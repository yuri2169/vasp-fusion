"""`make model`: dataset.csv -> the model, its measurements, its plots and the label
scores, all under `artifacts/model_v1/<chain>/`. And the shape /api/model serves.

Everything written here except `model.pkl` is tracked in git and comes out the same
on every run (`trained_at` aside), so a number in a report can be traced to a file.
"""
from __future__ import annotations

import json
from pathlib import Path

from .dataset import Run, read_dataset
from .explain import FEATURE_NAMES, importance_svg, reliability_svg
from .score import score_labels, write_scores
from .train import SEED, Result, run, save

SPLIT = "by time, and by exchange (leave one exchange out)"


def notes(m: dict) -> list[str]:
    """What the numbers are and are not, in sentences a reader can quote."""
    d, t = m["dataset"], m["time_split"]["test"]
    pooled = m["leave_one_exchange_out"]["pooled"]
    cf = m["cross_fit"]["pooled"]
    ab = m["ablation_label_features"]
    ab_pooled = ab["leave_one_exchange_out"]["pooled"]
    return [
        f"Trained on {d['addresses']:,} real {m['chain']} addresses: {d['positive']:,} deposit "
        f"addresses and {d['negative']:,} others. The model reads what an address does "
        "(forwarding, timing, who pays its fees), never a label.",
        f"By time (latest {t['n']:,} addresses, unseen): PR-AUC {t['pr_auc']}, Brier "
        f"{t['brier']}, ECE {t['ece']}.",
        f"By exchange: each exchange's addresses ({pooled['n']:,} in total) were scored by a "
        f"model that never saw that exchange. Pooled PR-AUC {pooled['pr_auc']}, recall "
        f"{pooled['at_0_5']['recall']} and precision {pooled['at_0_5']['precision']} at 0.5.",
        f"The scores the labels carry are cross-fit: each address is scored by a model that "
        f"never trained on it but knows its exchange from the exchange's other addresses. "
        f"On all {cf['n']:,} addresses: PR-AUC {cf['pr_auc']}, Brier {cf['brier']}, ECE "
        f"{cf['ece']}.",
        "Probabilities are calibrated with Venn-Abers on addresses the trees did not train on, "
        "at this dataset's class mix (the negatives are a capped sample), not at the mix of "
        "the chain at large.",
        "The two features that read exchange labels were left out of the shipped model: with "
        f"them it scores PR-AUC {ab['time_split']['pr_auc']} by time, because the positives "
        "were picked by those labels, and recall "
        f"{ab_pooled['at_0_5']['recall']} on an exchange whose labels are hidden.",
        "A label's confidence is this probability times the weight of the exchange wallet's "
        "own label. That weight, the hop decay and the share factor are still rule-set.",
    ]


def model_info(m: dict) -> dict:
    """metrics.json -> the API's ModelInfo."""
    t = m["time_split"]["test"]
    return {
        "status": "measured", "version": m["version"], "trained_at": m.get("trained_at"),
        "split": SPLIT, "chain": m["chain"],
        "metrics": {"pr_auc": t["pr_auc"], "ece": t["ece"], "brier": t["brier"],
                    "accuracy_when_answering": t["confident"]["accuracy"],
                    "coverage": t["confident"]["coverage"], "n_test": t["n"]},
        "reliability": t["reliability"],
        "risk_coverage": t["risk_coverage"],
        "feature_importance": [{"feature": FEATURE_NAMES[f["feature"]],
                                "importance": f["importance"]}
                               for f in m["feature_importance"]],
        "leave_one_exchange_out": [
            {k: row[k] for k in ("exchange", "n", "n_positive", "pr_auc", "roc_auc", "brier",
                                 "ece", "precision", "recall")}
            for row in m["leave_one_exchange_out"]["folds"]],
        "notes": m.get("notes") or notes(m),
    }


def build_model(chain: str, out_dir: Path | str, runs: list[Run], trained_at: str,
                seed: int = SEED) -> tuple[Result, list[dict]]:
    """Train on `<out_dir>/<chain>/dataset.csv` and write every artefact next to it.
    `runs` are the chain's discovery runs: their derived addresses get a score."""
    out = Path(out_dir) / chain
    df = read_dataset(out / "dataset.csv")
    result = run(df, seed=seed)
    result.metrics["notes"] = notes(result.metrics)
    result.metrics["trained_at"] = trained_at
    save(result, out)
    m = result.metrics
    t = m["time_split"]["test"]
    pooled = m["leave_one_exchange_out"]["pooled"]
    (out / "reliability.svg").write_text(reliability_svg(
        t["reliability"], f"{chain}, latest {t['n']:,} addresses", t["ece"], t["brier"]))
    (out / "reliability_by_exchange.svg").write_text(reliability_svg(
        pooled["reliability"], f"{chain}, each exchange scored unseen", pooled["ece"],
        pooled["brier"]))
    cf = m["cross_fit"]["pooled"]
    (out / "reliability_labels.svg").write_text(reliability_svg(
        cf["reliability"], f"{chain}, the scores the labels carry", cf["ece"], cf["brier"]))
    (out / "importance.svg").write_text(importance_svg(m["feature_importance"], chain))
    scores = score_labels(df, result, runs) if runs else []
    if scores:
        write_scores(out / "scores.csv", scores)
    return result, scores


def read_metrics(model_dir: Path | str, chain: str) -> dict | None:
    path = Path(model_dir) / chain / "metrics.json"
    return json.loads(path.read_text()) if path.exists() else None
