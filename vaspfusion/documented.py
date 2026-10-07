"""The recorded cases that are publicly documented incidents, with their sources.

demo/cases.json marks such a case with a `documented` block: what happened in the words
of the cited sources, one sentence on what the trace shows and what it does not, and the
sources. It is served beside the case (never stored with it), so the landing page and
the case page can show where the address comes from.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "demo" / "cases.json"


@lru_cache(maxsize=4)
def _load(path: str) -> dict[str, dict]:
    try:
        specs = json.loads(Path(path).read_text())["cases"]
    except (OSError, ValueError, KeyError):
        return {}
    return {s["id"]: s["documented"] for s in specs if s.get("documented")}


def documented_for(case_id: str, path: Path | str | None = None) -> dict | None:
    """The `DocumentedCase` of a recorded case, or None."""
    return _load(str(path or os.environ.get("VASPFUSION_DEMO_CASES") or DEFAULT_PATH)).get(case_id)
