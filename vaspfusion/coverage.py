"""The problem statement, line by line, with what the tool does about each line.

The rows are data (data/ps_coverage.yaml). Nothing here decides a status, with one
exception: a row marked `computed: chains` is worked out from the chains the tool can
trace today, so it cannot claim a chain that does not trace and turns to "built" by
itself when the missing ones land.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "ps_coverage.yaml"
STATUSES = ("built", "partly", "planned")
# How the problem statement spells a chain, where it differs from how the tool does.
CHAIN_NAMES = {"bsc": "BNB Chain", "bitcoin": "Bitcoin", "ethereum": "Ethereum", "tron": "Tron",
               "solana": "Solana", "polygon": "Polygon", "arbitrum": "Arbitrum", "base": "Base",
               "optimism": "Optimism", "avalanche": "Avalanche"}


class CoverageError(ValueError):
    """The coverage file says something it may not say."""


def _name(chain: str) -> str:
    return CHAIN_NAMES.get(chain, chain.capitalize())


def _list(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


@lru_cache(maxsize=4)
def _load(path: str) -> tuple[dict, ...]:
    rows = (yaml.safe_load(Path(path).read_text()) or {}).get("rows") or []
    seen: set[str] = set()
    for row in rows:
        rid = row.get("id")
        if not rid or rid in seen:
            raise CoverageError(f"coverage row id missing or repeated: {rid!r}")
        seen.add(rid)
        for key in ("section", "text", "where", "evidence"):
            if not row.get(key):
                raise CoverageError(f"coverage row {rid} has no {key}")
        ev = row["evidence"]
        if not isinstance(ev, dict) or len(ev) != 1 or next(iter(ev)) not in ("test", "make"):
            raise CoverageError(f"coverage row {rid}: evidence is one of test: or make:")
        if row.get("computed"):
            if row["computed"] != "chains" or not row.get("named_chains"):
                raise CoverageError(f"coverage row {rid}: computed rows name their chains")
            continue
        if row.get("status") not in STATUSES:
            raise CoverageError(f"coverage row {rid}: status must be one of {STATUSES}")
        if not row.get("what"):
            raise CoverageError(f"coverage row {rid} does not say what exists")
        if row["status"] != "built" and not row.get("gap"):
            raise CoverageError(f"coverage row {rid} is not built and does not say what is missing")
    return tuple(rows)


def load(path: Path | str | None = None) -> list[dict]:
    return [dict(r) for r in _load(str(path or DEFAULT_PATH))]


def _chain_row(row: dict, traceable: tuple[str, ...]) -> dict:
    named = row["named_chains"]
    works = [c for c in named if c in traceable]
    missing = [c for c in named if c not in traceable]
    others = [c for c in traceable if c not in named]
    what = f"Wallets are traced on {_list([_name(c) for c in works])}" if works \
        else "No chain the problem statement names can be traced"
    if others and works:
        what += f", and on {_list([_name(c) for c in others])}"
    status = "built" if not missing else "partly" if works else "planned"
    gap = None if not missing else (
        f"{_list([_name(c) for c in missing])} cannot be traced yet: a wallet on "
        f"{'that chain' if len(missing) == 1 else 'those chains'} is refused with a sentence.")
    return {"status": status, "what": what + ".", "gap": gap}


def build(traceable: tuple[str, ...], path: Path | str | None = None) -> dict:
    """`PsCoverage`: the rows as shown, and how many are built, partly built and planned."""
    rows = []
    for row in load(path):
        if row.get("computed") == "chains":
            row = {**row, **_chain_row(row, traceable)}
        kind, ref = next(iter(row["evidence"].items()))
        rows.append({"id": row["id"], "section": row["section"], "text": row["text"],
                     "status": row["status"], "what": row["what"], "where": row["where"],
                     "evidence_kind": kind, "evidence": ref, "gap": row.get("gap"),
                     "computed": bool(row.get("computed"))})
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    return {"rows": rows, "counts": counts, "total": len(rows),
            "traceable_chains": list(traceable),
            "source": "Smart India Hackathon problem statement 26182 (Ministry of Home "
                      "Affairs, I4C), quoted word for word."}
