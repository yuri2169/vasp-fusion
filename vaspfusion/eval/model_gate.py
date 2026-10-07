"""Should a chain's deposit-address model be used when tracing? Decided by a rule that
was fixed before the numbers were looked at.

At runtime the model only produces leads: an unlabelled wallet on the trail scoring at
or above the lead bar is flagged as behaving like a deposit address. A lead is about an
exchange the tool holds no label for, so the held-out data that matches it is the
leave-one-exchange-out predictions: each address scored by a model that never saw its
exchange.

Rule: the chain is switched on only if at least `MIN_FLAGGED` held-out addresses score
at or above the lead bar AND the one-sided 95% Clopper-Pearson upper bound of the share
of them that are not deposit addresses is no higher than the reference: the upper bound
of the naming error measured on Tron at the bar in use (abstain_v1).
"""
from __future__ import annotations

import polars as pl

from ..attribute.leads import LeadConfig
from ..classify.train import FEATURES, SEED, _by_exchange
from .benchmark import upper_bound

MIN_FLAGGED = 30


def held_out_leads(df: pl.DataFrame, bar: float, seed: int = SEED,
                   min_positives: int = 20) -> dict:
    df = df.sort("address")
    _, _, oof = _by_exchange(df, FEATURES, seed, hide=False, min_positives=min_positives)
    scored = df.select("address", "y").join(oof.select("address", "fold", "p"), on="address")
    flagged = scored.filter(pl.col("p") >= bar)
    wrong = int((flagged["y"] == 0).sum())
    folds = [{"exchange": f, "held_out": int(len(g)), "deposit_addresses": int(g["y"].sum()),
              "flagged": int((g["p"] >= bar).sum()),
              "flagged_wrong": int(((g["p"] >= bar) & (g["y"] == 0)).sum())}
             for (f,), g in sorted(scored.group_by("fold"), key=lambda kv: kv[0][0])]
    positives = int(scored["y"].sum())
    return {"held_out": int(len(scored)), "deposit_addresses": positives,
            "flagged": int(len(flagged)), "flagged_wrong": wrong,
            "error": round(wrong / len(flagged), 4) if len(flagged) else None,
            "error_upper_95": upper_bound(wrong, int(len(flagged))),
            "deposit_addresses_found": round((len(flagged) - wrong) / positives, 4)
            if positives else None,
            "folds": folds}


def decide(chain: str, df: pl.DataFrame, reference_upper: float,
           bar: float | None = None) -> dict:
    bar = LeadConfig().min_p if bar is None else bar
    m = held_out_leads(df, bar)
    enough = m["flagged"] >= MIN_FLAGGED
    within = m["error_upper_95"] is not None and m["error_upper_95"] <= reference_upper
    why = (f"only {m['flagged']} held-out addresses were flagged; the rule needs {MIN_FLAGGED}"
           if not enough else
           f"the upper bound of the error among the flagged, {m['error_upper_95']:.1%}, is "
           + ("within" if within else "above") + f" the reference {reference_upper:.1%}")
    return {"chain": chain, "lead_bar": bar, "reference_upper": reference_upper,
            "min_flagged": MIN_FLAGGED, "switch_on": bool(enough and within), "because": why,
            "rule": "switch on only if at least 30 leave-one-exchange-out addresses score at "
                    "or above the lead bar and the one-sided 95% upper bound of the share of "
                    "them that are not deposit addresses is no higher than the upper bound "
                    "of the naming error measured on Tron at the 0.60 bar",
            **m}
