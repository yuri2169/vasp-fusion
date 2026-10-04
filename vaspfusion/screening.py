"""Screening on intake: is the address itself on a threat list?

One label lookup, done when a case is opened and before any chain is read, so a direct
hit is on the officer's screen at once. It says only what the label store holds: a tag
with its source, or that the address carries none. Links found further along the trail
are the trace's to report (the `threat_contact` flag), not this check's.
"""
from __future__ import annotations

from .labels.threats import named, tag_of, threats

RISK_CATEGORIES = {"sanctioned": "sanctioned", "mixer": "a mixer", "scam": "a scam address"}


def screen(label) -> dict:
    """`Screening` for the label of a case's own address (a `Label`, its dict, or None)."""
    tag = tag_of(label)
    if tag is not None:
        return {"hit": True, "tag": tag,
                "text": f"Direct hit: this address is tagged {named(tag)}."}
    get = (label.get if isinstance(label, dict) else lambda k: getattr(label, k, None)) \
        if label is not None else (lambda k: None)
    if get("category") in RISK_CATEGORIES:
        return {"hit": True, "tag": None,
                "text": f"Direct hit: this address is labelled {RISK_CATEGORIES[get('category')]} "
                        f"({get('entity')}; source: {get('source')})."}
    return {"hit": False, "tag": None,
            "text": "No direct hit: the address itself carries no ransomware, darknet-market, "
                    "terrorism-financing, fraud or sanctions tag in the label store."}


def case_threats(origin_tag: dict | None, flags: list[dict]) -> list[str]:
    """The distinct threats a case touches (its own address, or a flagged link), most
    specific first."""
    found = {t["threat"] for t in [origin_tag, *(f.get("threat") for f in flags)] if t}
    return [t for t in threats() if t in found]
