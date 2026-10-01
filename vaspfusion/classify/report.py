"""`make model`: dataset.csv -> the model, its measurements, its plots and the label
scores, all under `artifacts/model_v1/<chain>/`. And the shape /api/model serves.

Everything written here except `model.pkl` is tracked in git and comes out the same
on every run (`trained_at` aside), so a number in a report can be traced to a file.
"""
from __future__ import annotations

import hashlib
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
    by_rules = "derived" in d["by_source"]
    truth = ("The deposit addresses are the ones the discovery rules derived, so these numbers "
             "say how well behaviour alone recovers what rules and labels found; they are not "
             "an accuracy against an outside truth."
             if by_rules else
             "The deposit addresses are the ones a block explorer tagged, a truth our rules "
             "never saw.")
    la = m["time_split"]["look_alikes"]
    base = m["time_split"]["baseline_forward_rule"]
    customers = d["by_source"].get("customer", 0)
    return [
        f"Trained on {d['addresses']:,} real {m['chain']} addresses: {d['positive']:,} deposit "
        f"addresses and {d['negative']:,} others. The model reads what an address does "
        f"(forwarding, timing, who pays its fees), never a label. {truth}",
        f"By time (latest {t['n']:,} addresses by first transfer, unseen): PR-AUC "
        f"{t['pr_auc']}, Brier {t['brier']}, ECE {t['ece']}, precision "
        f"{t['at_0_5']['precision']} and recall {t['at_0_5']['recall']} at 0.5. The rule "
        f"\"forwards 90% or more to one wallet\" alone gives precision {base['precision']} "
        f"and recall {base['recall']} on the same addresses: that, not chance, is the bar.",
        f"By exchange: each exchange's addresses ({pooled['n']:,} in total) were scored by a "
        f"model that never saw that exchange. Pooled PR-AUC {pooled['pr_auc']}, recall "
        f"{pooled['at_0_5']['recall']} and precision {pooled['at_0_5']['precision']} at 0.5.",
        f"The scores the labels carry are cross-fit: each address is scored by a model that "
        f"never trained on it but knows its exchange from the exchange's other addresses. "
        f"On all {cf['n']:,} addresses: PR-AUC {cf['pr_auc']}, Brier {cf['brier']}, ECE "
        f"{cf['ece']}. Most of those models also trained on later addresses, so this "
        "describes the scores; it is not an accuracy to expect on new addresses.",
        "Probabilities are calibrated with Venn-Abers on addresses the trees did not train on, "
        "at this dataset's class mix (the negatives are a capped sample), not at the mix of "
        "the chain at large.",
        f"The hard case, by time: of the {la['negatives']:,} other wallets that also forward "
        f"{la['forwarding_at_least']:.0%} or more of what they receive to one wallet, the model "
        f"still calls {la['flagged']:,} a deposit address "
        f"({m['leave_one_exchange_out']['look_alikes']['flagged']:,} of "
        f"{m['leave_one_exchange_out']['look_alikes']['negatives']:,} by exchange, "
        f"{m['cross_fit']['look_alikes']['flagged']:,} of "
        f"{m['cross_fit']['look_alikes']['negatives']:,} cross-fit).",
        f"{customers:,} of the {d['negative']:,} others are wallets that paid into the deposit "
        "addresses; the rest are labelled wallets that are not deposit addresses. A wallet "
        "that never dealt with an exchange is not in this sample, so how often the model "
        "would take such a wallet for a deposit address is not measured here.",
        "The two features that read exchange labels were left out of the shipped model: with "
        f"them it scores PR-AUC {ab['time_split']['pr_auc']} by time"
        + (", because the positives were picked by those labels," if by_rules else "")
        + f" and recall {ab_pooled['at_0_5']['recall']} on an exchange whose labels are hidden"
        + (" (near zero by construction: without the labels those features say nothing)."
           if by_rules else "."),
        "A derived label carries the model's value (the weight of the exchange wallet's own "
        "label times this probability, with its range) when that is at least what the "
        "discovery rules gave it; otherwise the rules' confidence is kept. The model can "
        "confirm a label; it cannot overrule label evidence it does not see. The label "
        "weights, the hop decay and the share factor are still rule-set.",
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
        "look_alikes": m["time_split"]["look_alikes"],
        "baseline": {k: m["time_split"]["baseline_forward_rule"][k]
                     for k in ("rule", "precision", "recall", "accuracy")},
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
    # which dataset these numbers and scores were made from
    result.metrics["dataset"]["sha256"] = hashlib.sha256(
        (out / "dataset.csv").read_bytes()).hexdigest()
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
