"""Wallet and flow risk: an indicator score, built from what a case already found.

An indicator score from published red-flag rules. Not a probability. What it does on real
listed and ordinary wallets is measured by eval/risk_validation.py (`make risk-validation`);
the sentence that travels with the score (`RISK_BASIS`) quotes that file. Each indicator present adds its points (config/risk.yaml); the
score is their sum, capped at 100, and the class is read off the score. Every indicator
carries the sentence it rests on and the transactions behind it.

Nothing here reads a chain. A case's risk is worked out from its stored typology flags,
labels and "where the funds went" slices each time the case is read, and is never stored
with it, so it is no part of the case's digests: changing the points changes the score
of every case at once, without tracing anything again.

Three rules, held by tests/test_risk.py: an indicator counts once however often it is
seen; adding an indicator never lowers the score; the same case gives the same score.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

from .api.schemas import RISK_BASIS
from .labels.threats import named as threat_words
from .labels.threats import tag_of

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "config" / "risk.yaml"
CLASSES = ("low", "medium", "high", "severe")
RANK = {c: i for i, c in enumerate(CLASSES)}
# a typology flag -> the indicator it is counted as; the label flags are split by side below
PATTERNS = ("coinjoin_shape", "peel_chain", "rapid_forwarding", "fan_out", "fan_in",
            "round_amounts")
# The pattern rules that read only how money moved. Together they add at most
# `pattern_cap` points (config/risk.yaml): measured on real wallets, each fired on
# ordinary wallets as often as on listed ones, so by themselves they must not lift a
# wallet out of Low.
CAPPED = ("peel_chain", "rapid_forwarding", "fan_out", "fan_in", "round_amounts")
# threat_contact: a link to an address with a threat tag that is neither sanctioned nor a
# mixer (typologies.py raises one flag per address, so nothing is counted twice)
LABEL_FLAGS = {"sanctioned_contact": "sanctioned", "mixer_contact": "mixer",
               "threat_contact": "threat"}
SELF = {"sanctioned": "is on a sanctions list", "mixer": "is labelled as a mixer",
        "scam": "is on a scam list"}
CODES = ("sanctioned_self", "sanctioned_contact", "sanctioned_funding", "mixer_self",
         "mixer_contact", "mixer_funding", "threat_self", "threat_contact", "threat_funding",
         "coinjoin_shape", "scam_self", "scam_contact",
         "bridge_hop", "swap_service", "peel_chain", "rapid_forwarding", "fan_out", "fan_in",
         "round_amounts", "unlabelled_hub")


class RiskConfigError(ValueError):
    """config/risk.yaml breaks its own rules."""


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    doc = yaml.safe_load(Path(path).read_text()) or {}
    classes, inds, src = doc.get("classes") or {}, doc.get("indicators") or {}, doc.get("source") or {}
    if list(classes) != list(CLASSES) or classes["low"] != 0 or \
            not all(isinstance(v, int) for v in classes.values()) or \
            sorted(classes.values()) != list(classes.values()) or \
            len(set(classes.values())) != 4 or classes["severe"] > 100:
        raise RiskConfigError("classes must be low: 0 < medium < high < severe <= 100")
    missing = [c for c in CODES if c not in inds]
    if missing:
        raise RiskConfigError(f"indicators missing: {', '.join(missing)}")
    for code, ind in inds.items():
        for key in ("points", "extra"):
            v = ind.get(key, 0)
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 100:
                raise RiskConfigError(f"{code}.{key} must be a whole number from 0 to 100")
        if not ind.get("name") or not ind.get("fatf_category"):
            raise RiskConfigError(f"{code} needs a name and a fatf_category")
    weights = doc.get("distance_weight")
    if not isinstance(weights, list) or len(weights) != 3 or \
            not all(isinstance(w, (int, float)) and 0 <= w <= 1 for w in weights):
        raise RiskConfigError("distance_weight must be three numbers from 0 to 1")
    if not src.get("title") or not src.get("url") or not src.get("publisher"):
        raise RiskConfigError("source needs a title, a publisher and a url")
    cap = doc.get("pattern_cap")
    if cap is not None and (not isinstance(cap, int) or isinstance(cap, bool) or not 0 <= cap <= 100):
        raise RiskConfigError("pattern_cap must be a whole number from 0 to 100")
    return {"classes": dict(classes), "indicators": inds, "distance_weight": list(weights),
            "pattern_cap": cap,
            "source": f"{src['publisher']}, \"{src['title']}\", {src.get('published')}"}


def load_config(path: Path | str | None = None) -> dict:
    return _load(str(path or os.environ.get("VASPFUSION_RISK") or DEFAULT_PATH))


def class_of(score: int, cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    return max((c for c in CLASSES if score >= cfg["classes"][c]), key=RANK.__getitem__)


def _short(a: str) -> str:
    chain, sep, plain = a.partition(":")    # a wallet on another chain: `chain:address`
    if sep:
        return f"{_short(plain)} on {chain.title()}"
    return a if len(a) <= 14 else f"{a[:6]}…{a[-6:]}"


def _ref(case: dict) -> str:
    return case.get("case_ref") or case["id"]


def _points(cfg: dict, code: str, share: float = 0.0, hops: float = 1.0) -> int:
    ind = cfg["indicators"][code]
    w = cfg["distance_weight"][min(max(int(hops), 1), 3) - 1]
    return min(100, ind["points"] + round(ind.get("extra", 0) * max(0.0, min(1.0, share)) * w))


def _inbound_only(case: dict, wallet: str) -> bool:
    """Is this wallet only on the funding side of the case (it paid in, never got paid)?"""
    sides = {e.get("direction", "outbound") for e in case.get("graph", {}).get("edges", [])
             if wallet in (e["source"], e["target"])}
    return sides == {"inbound"}


def _found(case: dict, cfg: dict) -> list[dict]:
    """Every instance of an indicator in a finished case, before the same kind is merged."""
    out: list[dict] = []

    def add(code: str, text: str, wallet: str | None, hashes, share=0.0, hops=1.0) -> None:
        out.append({"code": code, "points": _points(cfg, code, share, hops), "text": text,
                    "wallet": wallet, "tx_hashes": sorted(set(hashes))})

    for f in case.get("typology_flags", []):
        code, fig = f["code"], f.get("figures") or {}
        if code in LABEL_FLAGS:
            kind = LABEL_FLAGS[code]
            if f["wallet"] == case["address"] and "share" not in fig:
                code = f"{kind}_self"
            elif _inbound_only(case, f["wallet"]):
                code = f"{kind}_funding"
            else:
                code = f"{kind}_contact"
        elif code == "bridge_hop":
            if _inbound_only(case, f["wallet"]):
                continue                    # money that arrived over a bridge is not a red flag here
        elif code not in PATTERNS:
            continue                        # deposit_like is a lead, not a risk
        add(code, f["text"], f["wallet"], f.get("tx_hashes", []),
            fig.get("share", 0.0), fig.get("hops", 1.0) if code.endswith(("contact", "hop")) else 1.0)

    edges = case.get("graph", {}).get("edges", [])
    for n in case.get("graph", {}).get("nodes", []):
        lab = n.get("label") or {}
        cat = lab.get("category")
        named = lab.get("label") or lab.get("entity") or cat
        touching = [e["tx_hash"] for e in edges if n["id"] in (e["source"], e["target"])]
        if cat == "scam" and tag_of(lab) is None:     # a tagged one is a threat_contact flag
            mine = n["id"] == case["address"]
            add("scam_self" if mine else "scam_contact",
                f"{'The wallet itself' if mine else _short(n['id'])} is on a scam list: "
                f"{named} (source: {lab.get('source')})", n["id"], touching)
        elif cat == "swap_service" and n["id"] != case["address"]:
            paid = [e["tx_hash"] for e in edges
                    if e["target"] == n["id"] and e.get("direction", "outbound") == "outbound"]
            if paid:
                add("swap_service", f"Funds went into a swap service, {_short(n['id'])} "
                                    f"({named})", n["id"], paid)

    hub = sum(s["share"] for s in case.get("where_funds_went", []) if s["kind"] == "hub")
    if hub >= cfg["indicators"]["unlabelled_hub"].get("min_share", 0.5):
        hubs = {n["id"] for n in case.get("graph", {}).get("nodes", []) if n.get("is_hub")}
        add("unlabelled_hub", f"{round(hub * 100)}% of the funds stopped at unlabelled wallets "
                              "with a great many counterparties, where the trail cannot be "
                              "followed further", None,
            [e["tx_hash"] for e in edges if e["target"] in hubs
             and e.get("direction", "outbound") == "outbound"])
    return out


def _merge(found: list[dict], cfg: dict) -> list[dict]:
    """One entry per indicator: the largest instance, with every instance's transactions."""
    by: dict[str, list[dict]] = {}
    for inst in found:
        by.setdefault(inst["code"], []).append(inst)
    merged = []
    for code, group in by.items():
        group.sort(key=lambda i: (-i["points"], i["wallet"] or "", i["text"]))
        top = group[0]
        more = len(group) - 1
        ind = cfg["indicators"][code]
        merged.append({
            "code": code, "name": ind["name"], "points": top["points"],
            "text": top["text"] + (f" (and {more} more of this kind)" if more else ""),
            "fatf_category": ind["fatf_category"], "wallet": top["wallet"],
            "case_id": top.get("case_id"),
            "tx_hashes": sorted({h for i in group for h in i["tx_hashes"]})})
    merged.sort(key=lambda i: (-i["points"], CODES.index(i["code"])))
    return merged


def total(points: dict[str, int], cfg: dict) -> int:
    """The score of a set of indicators (code -> points): their sum, with the pattern
    rules together counted up to `pattern_cap`, capped at 100. Adding an indicator never
    lowers it."""
    patterns = sum(p for c, p in points.items() if c in CAPPED)
    cap = cfg.get("pattern_cap")
    if cap is not None:
        patterns = min(patterns, cap)
    return min(100, patterns + sum(p for c, p in points.items() if c not in CAPPED))


def _info(indicators: list[dict], cfg: dict, **extra) -> dict:
    score = total({i["code"]: i["points"] for i in indicators}, cfg)
    return {"score": score, "risk_class": class_of(score, cfg), "indicators": indicators,
            "reasons": [i["text"] for i in indicators], "flows": [], "path_class": None,
            "basis": RISK_BASIS, "source": cfg["source"], **extra}


def _flows(case: dict, found: list[dict], cfg: dict) -> tuple[list[dict], str | None]:
    """Each traced transfer by the indicators on it: the ones whose transactions include
    it. A transfer with none is Low and is not listed."""
    by_hash: dict[str, dict[str, int]] = {}
    for inst in found:
        for h in inst["tx_hashes"]:
            codes = by_hash.setdefault(h, {})
            codes[inst["code"]] = max(codes.get(inst["code"], 0), inst["points"])

    def grade(codes: dict[str, int]) -> tuple[str, list[str]]:
        ranked = sorted(codes, key=lambda c: (-codes[c], CODES.index(c)))
        return (class_of(total(codes, cfg), cfg),
                [cfg["indicators"][c]["name"] for c in ranked])

    flows = []
    for e in case.get("graph", {}).get("edges", []):
        codes = by_hash.get(e["tx_hash"])
        if not codes:
            continue
        klass, reasons = grade(codes)
        if klass != "low":
            flows.append({"edge_id": e["id"], "tx_hash": e["tx_hash"], "risk_class": klass,
                          "reasons": reasons})
    rail = case.get("hop_rail") or []
    on_path: dict[str, int] = {}
    for h in rail:
        for code, pts in by_hash.get(h["tx_hash"], {}).items():
            on_path[code] = max(on_path.get(code, 0), pts)
    return flows, (grade(on_path)[0] if rail else None)


def case_risk(case: dict, cfg: dict | None = None) -> dict | None:
    """`RiskInfo` of a finished case: the traced wallet's indicators, and each transfer's
    class. None for a case with no result."""
    if case.get("status") != "done" or "candidates" not in case or case.get("outcome") is None:
        return None
    cfg = cfg or load_config()
    found = _found(case, cfg)
    flows, path = _flows(case, found, cfg)
    return _info(_merge(found, cfg), cfg, flows=flows, path_class=path)


def summary(case: dict | None, cfg: dict | None = None) -> dict:
    """The two fields a case summary carries."""
    risk = case_risk(case, cfg) if case else None
    return {"risk_class": risk["risk_class"] if risk else None,
            "risk_score": risk["score"] if risk else None}


def wallet_risk(address: str, label: dict | None, cases: list[dict],
                cfg: dict | None = None) -> dict:
    """`RiskInfo` of one address: its own label, the pattern flags that name it in any
    stored case, and, where it is the wallet a case traced, that case's indicators.
    Not assessed (class null) when it has no label and is in no finished case."""
    cfg = cfg or load_config()
    done = [c for c in cases if c.get("status") == "done"]
    if not label and not done:
        return {"score": None, "risk_class": None, "indicators": [], "reasons": [], "flows": [],
                "path_class": None, "basis": RISK_BASIS, "source": cfg["source"]}
    found: list[dict] = []
    cat = (label or {}).get("category")
    tag = tag_of(label) if label else None
    said = f" {tag['evidence']}" if tag and tag.get("evidence") else ""   # the source's own words
    tagged = f" It is tagged {threat_words(tag)}.{said}" if tag else ""
    if cat in SELF and not (cat == "scam" and tag):
        named = label.get("label") or label.get("entity")
        code = f"{cat}_self"
        found.append({"code": code, "points": _points(cfg, code), "wallet": address,
                      "tx_hashes": [], "text": f"This address {SELF[cat]}: {named} "
                                               f"(source: {label['source']}).{tagged}"})
    elif tag:
        found.append({"code": "threat_self", "points": _points(cfg, "threat_self"),
                      "wallet": address, "tx_hashes": [],
                      "text": f"This address is tagged {threat_words(tag)}.{said}"})
    for case in done:
        if case.get("address") == address:
            mine = [i for i in _found(case, cfg) if not i["code"].endswith("_self")]
        else:       # a wallet on someone else's trail: only what was seen of it
            mine = [i for i in _found(case, cfg)
                    if i["wallet"] == address and i["code"] in PATTERNS]
        found += [{**i, "case_id": case["id"], "text": f"Case {_ref(case)}: {i['text']}"}
                  for i in mine]
    return _info(_merge(found, cfg), cfg)
