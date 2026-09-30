"""SHAP attributions -> prose an analyst can read.

Explainability is a graded deliverable, not garnish, and the user is a person who
reads briefings rather than feature vectors. A ranked list of
`chain_depth_max: +0.24` explains nothing to the person who has to defend the
decision to their own boss.

So every feature carries the sentence describing what real-world behaviour it
captures - the same sentence the roadmap requires as its docstring discipline
(§6.5). If a feature cannot be given one, it should be deleted rather than
explained away.

The narrative states the direction of each contribution, never just its
magnitude, because "unusually FEW counterparties" and "unusually MANY" mean
opposite things and a bare importance score cannot tell them apart.
"""
from __future__ import annotations

import numpy as np

# feature -> (phrase when the value is HIGH, phrase when the value is LOW)
PHRASES: dict[str, tuple[str, str]] = {
    "chain_linearity": ("funds travel down a long, narrow chain rather than spreading out",
                        "funds stay within a compact, well-connected neighbourhood"),
    "reach_3": ("reaches an unusually large number of entities within three hops",
                "reaches very few entities within three hops"),
    "peel_ratio_mean": ("repeatedly splits off small amounts and forwards the remainder - "
                        "the peeling-chain signature",
                        "splits value evenly rather than peeling"),
    "two_output_frac": ("almost every spend has exactly two outputs, consistent with a "
                        "payment-plus-change or peel pattern",
                        "spends have varied output counts"),
    # NOTE the direction: entropy is MAXIMAL when outputs share one value, so
    # high entropy is the mixer signal and low entropy means one output dominates.
    "output_entropy_mean": ("output values are evenly sized across payments, as a "
                            "mixer's equal-value outputs would be",
                            "one output dominates the value in a typical payment - "
                            "the peel-chain shape"),
    "output_entropy_min": ("even the least uniform transaction pays evenly sized outputs",
                           "at least one transaction sends nearly all its value to a "
                           "single output"),
    "output_uniformity_max": ("at least one transaction pays the identical amount to many "
                              "outputs - the CoinJoin/mixer fingerprint",
                              "no transaction repeats an output value"),
    "output_uniformity_mean": ("output values are habitually repeated across payments",
                               "output values are essentially always distinct"),
    "script_uniformity": ("every output uses the same script type, which is unusual for "
                          "organic payments and typical of mixers",
                          "output script types are mixed, as in normal payment traffic"),
    "burstiness": ("activity arrives in tight bursts rather than at a steady rate",
                   "activity is unusually regular, closer to automated scheduling"),
    "dormancy_ratio": ("most of this entity's lifespan is a single dormant gap followed "
                       "by sudden movement",
                       "activity is spread across the observed window"),
    "gap_mean": ("long intervals between spends",
                 "hops follow each other within minutes - rapid layering, minimal dwell"),
    "hour_entropy": ("activity is spread evenly around the clock, as automated "
                     "infrastructure would be",
                     "activity is concentrated in a narrow band of hours, consistent with "
                     "a single human operator"),
    "counterparty_hhi": ("value is concentrated on very few counterparties",
                         "value is spread across many counterparties"),
    "n_counterparties_out": ("pays an unusually large number of distinct entities",
                             "pays very few distinct entities"),
    "max_n_outputs": ("at least one transaction fans value out across many outputs at once",
                      "transactions have few outputs"),
    "mean_n_inputs": ("consolidates many inputs per spend", "spends single inputs"),
    "structuring_proximity": ("amounts sit just below a round threshold, consistent with "
                              "deliberate structuring",
                              "amounts show no clustering below round thresholds"),
    "round_number_frac": ("amounts are frequently round numbers, suggesting human-chosen "
                          "sums rather than market pricing",
                          "amounts look market-priced"),
    "tor_frac": ("a large share of announcements came from Tor exit relays",
                 "little or no Tor usage"),
    "vpn_frac": ("a large share of announcements came from commercial VPN endpoints",
                 "little or no VPN usage"),
    "shared_infra_frac": ("announcements come mostly from shared infrastructure, which "
                          "weakens attribution",
                          "announcements come from addresses that are not obviously shared"),
    "residential_frac": ("announcements come from residential addresses, which supports "
                         "attribution to an individual operator",
                         "announcements do not come from residential addresses"),
    "n_asns": ("announcements are spread across many autonomous systems",
               "announcements come from a single network"),
    "n_countries": ("announcements originate in several countries",
                    "announcements originate in one country"),
    "ip_churn_rate": ("the announcing address changes often relative to activity",
                      "the announcing address is stable"),
    "listening_node_ratio": ("announces from port 8333, indicating an inbound-listening "
                             "node rather than a leaf wallet",
                             "announces from ephemeral ports, as a leaf wallet does"),
    "nonstandard_dst_port_frac": ("connects to non-standard ports, suggesting custom or "
                                  "deliberately evasive node configuration",
                                  "uses the standard Bitcoin port"),
    "pagerank": ("occupies a central position in the payment graph",
                 "sits at the periphery of the payment graph"),
    "betweenness_est": ("acts as a bridge between otherwise separate parts of the graph",
                        "does not bridge separate parts of the graph"),
    "degree_in": ("receives from many distinct sources", "receives from very few sources"),
    "degree_out": ("pays out to many destinations", "pays out to very few destinations"),
    "lifespan_days": ("has been active over a long window",
                      "was active only very briefly - a short-lived wallet"),
    "in_out_ratio": ("moves out far more than it takes in",
                     "retains most of what it receives"),
    "taproot_frac": ("uses Taproot outputs", "uses older output types"),
    "segwit_frac": ("uses SegWit outputs", "uses legacy output types"),
    "change_script_match_rate": ("change consistently matches the spending wallet's script "
                                 "type", "change often lands on a different script type"),
}


def phrase_for(feature: str, shap_value: float, value: float, median: float) -> str | None:
    """The English for one SHAP contribution, chosen by which side of typical it sits."""
    entry = PHRASES.get(feature)
    if entry is None:
        return None
    high, low = entry
    return high if value >= median else low


def build_narrative(feature_names: list[str], shap_row: np.ndarray, values: np.ndarray,
                    medians: np.ndarray, top_k: int = 5,
                    evidence: list[dict] | None = None,
                    attribution: dict | None = None) -> str:
    """Assemble the plain-English assessment shown at the top of a case file."""
    order = np.argsort(-np.abs(shap_row))[:top_k]
    clauses: list[str] = []
    for i in order:
        if shap_row[i] <= 0:
            continue      # only reasons the score went UP belong in the assessment
        p = phrase_for(feature_names[i], float(shap_row[i]),
                       float(values[i]), float(medians[i]))
        if p:
            clauses.append(p)
    if not clauses:
        clauses.append("its overall behavioural profile is atypical relative to the "
                       "population, without any single dominant factor")

    body = "This entity was flagged because " + clauses[0]
    if len(clauses) > 1:
        body += "; " + "; ".join(clauses[1:3])
    body += "."

    if evidence:
        names = sorted({e["typology"].replace("_", " ") for e in evidence})
        body += (f" Rule-based matchers independently corroborate the pattern as "
                 f"{', '.join(names)}, with specific transactions listed in the "
                 f"evidence chain.")

    # Name an address only when the engine did. A withheld lead still carries
    # candidates, and printing the top one here contradicted the engine's decision.
    status = attribution.get("status") if attribution else None
    if status == "ok" and attribution.get("candidates"):
        top = attribution["candidates"][0]
        body += (f" Announced from {top['ip']} (AS{top['asn']}, {top['asn_type']}"
                 + (f", {top['country']}" if top.get("country") != "ZZ" else "")
                 + f"), attributed at confidence {top['confidence']:.2f}.")
    elif status == "suppressed":
        why = attribution.get("note") or ("Every candidate address is shared infrastructure; "
                                          "no origin claim can be made honestly.")
        body += " No address is named. " + why
    elif status == "no_significant_link":
        body += (" No address is named: no entity–IP association survived FDR control.")
    return body


def shap_table(feature_names: list[str], shap_row: np.ndarray, values: np.ndarray,
               top_k: int = 8) -> list[dict]:
    order = np.argsort(-np.abs(shap_row))[:top_k]
    return [{
        "feature": feature_names[i],
        "contribution": round(float(shap_row[i]), 4),
        "value": round(float(values[i]), 4),
        "direction": "increases" if shap_row[i] > 0 else "decreases",
        "meaning": (PHRASES.get(feature_names[i], ("", ""))[0] or None),
    } for i in order]
