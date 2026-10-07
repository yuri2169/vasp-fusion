"""Which providers registered with FIU-IND the tool can name.

The list is one official document, copied into data/indian_exchanges.yaml. For each
provider on it this counts the labelled addresses the store holds under its name: on
which chains, at which tier, and whether a recorded case names it. A trace names an
exchange only by reaching one of its labelled wallets, so a provider with no exchange
label on a chain the tool traces cannot be named, and the table says so.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import yaml

from .lookup import LabelStore
from .normalize import TIER_RANK, VASP_CATEGORIES

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "data" / "indian_exchanges.yaml"
RECORDED_CASES = ROOT / "tests" / "fixtures" / "demo" / "expected.json"
SOURCE_FIELDS = ("title", "publisher", "url", "licence", "published", "accessed")


class ListError(ValueError):
    """The list file breaks its own rule."""


def load_list(path: Path | str = DEFAULT_PATH) -> dict:
    doc = yaml.safe_load(Path(path).read_text()) or {}
    source, providers = doc.get("source") or {}, doc.get("providers") or []
    for field in SOURCE_FIELDS:
        if not source.get(field):
            raise ListError(f"the source has no {field}")
    for field in ("published", "accessed"):
        if not isinstance(source[field], date):
            raise ListError(f"the source's {field} must be a date")
    for i, p in enumerate(providers, 1):
        if p.get("n") != i:
            raise ListError(f"entry {i} is out of the list's order (n = {p.get('n')})")
        if not isinstance(p.get("legal_name"), str) or not p["legal_name"].strip():
            raise ListError(f"entry {i} has no legal_name")
        names = p.get("names")
        if names is None:
            names = [p["trade_name"]] if p.get("trade_name") else []
        if not isinstance(names, list) or not all(isinstance(x, str) for x in names):
            raise ListError(f"entry {i}: names must be a list of names")
        p["names"] = names
    return {"source": source, "providers": providers}


def recorded_cases(path: Path | str = RECORDED_CASES) -> dict[str, list[str]]:
    """exchange name (lower case) -> the recorded demo cases that name it."""
    path = Path(path)
    out: dict[str, list[str]] = {}
    if not path.exists():
        return out
    for case_id, case in sorted(json.loads(path.read_text()).items()):
        if case.get("top_vasp"):
            out.setdefault(case["top_vasp"].lower(), []).append(case_id)
    return out


def _ordered(counts: dict[str, int]) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def coverage(store: LabelStore, traceable: tuple[str, ...], path: Path | str = DEFAULT_PATH,
             recorded: Path | str = RECORDED_CASES) -> dict:
    """`traceable`: the chains a trace can run on. A label filed as `evm` matches every
    EVM chain, so it counts as traceable."""
    listed = load_list(path)
    names = sorted({n.lower() for p in listed["providers"] for n in p["names"]})
    held = store.entity_breakdown(names)
    cases = recorded_cases(recorded)
    reach = set(traceable) | {"evm"}
    rows = []
    for p in listed["providers"]:
        keys = {n.lower() for n in p["names"]}
        mine = [h for h in held if h[0] in keys]
        vasp = [h for h in mine if h[1] in VASP_CATEGORIES]
        by_chain: dict[str, int] = {}
        by_tier: dict[str, int] = {}
        for _, _, chain, tier, n in vasp:
            by_chain[chain] = by_chain.get(chain, 0) + n
            by_tier[tier] = by_tier.get(tier, 0) + n
        traceable_labels = sum(n for c, n in by_chain.items() if c in reach)
        rows.append({
            "n": p["n"], "legal_name": p["legal_name"], "trade_name": p.get("trade_name"),
            "labels": sum(by_chain.values()),
            "traceable_labels": traceable_labels,
            "other_labels": sum(h[4] for h in mine if h[1] not in VASP_CATEGORIES),
            "by_chain": _ordered(by_chain),
            "by_tier": dict(sorted(by_tier.items(), key=lambda kv: -TIER_RANK[kv[0]])),
            "recorded_cases": sorted({c for k in keys for c in cases.get(k, [])}),
            "can_name": traceable_labels > 0,
        })
    src = listed["source"]
    return {
        "source": {**{k: src[k] for k in ("title", "publisher", "url", "licence")},
                   "published": src["published"].isoformat(),
                   "accessed": src["accessed"].isoformat()},
        "listed": len(rows),
        "can_name": sum(r["can_name"] for r in rows),
        "in_recorded_cases": sum(bool(r["recorded_cases"]) for r in rows),
        "providers": rows,
    }


def markdown(cov: dict) -> str:
    """The table for the README: only what `coverage` returned."""
    lines = ["| # | Registered entity | Trade name | Exchange labels held | Chains | Best tier "
             "| Recorded case | Can the tool name it? |", "|---|---|---|---|---|---|---|---|"]
    for r in cov["providers"]:
        chains = ", ".join(f"{c} {n:,}" for c, n in r["by_chain"].items()) or "none"
        tier = next(iter(r["by_tier"]), "none")
        cases = ", ".join(f"`{c}`" for c in r["recorded_cases"]) or "none"
        lines.append(f"| {r['n']} | {r['legal_name']} | {r['trade_name'] or '(none listed)'} "
                     f"| {r['labels']:,} | {chains} | {tier} | {cases} "
                     f"| {'yes' if r['can_name'] else '**no**'} |")
    return "\n".join(lines) + "\n"
