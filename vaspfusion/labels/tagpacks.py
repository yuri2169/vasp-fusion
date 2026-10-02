"""GraphSense TagPacks (github.com/graphsense/graphsense-tagpacks, MIT) as a label source.

Only the exchange packs are used, and of those only the tags on chains this tool
traces. `read_packs` flattens the YAML (a pack's header fields are the default for
each of its tags) and `write_csv` writes the one CSV `make labels` reads, so the
336k-address BitMEX packs are parsed once, not on every label build.

    python -m vaspfusion.cli tagpacks --packs <research>/graphsense-tagpacks/packs
"""
from __future__ import annotations

import csv
from pathlib import Path

import yaml

COLUMNS = ["address", "currency", "actor", "label", "category", "source", "source_url",
           "lastmod"]
CURRENCIES = ("BTC", "ETH", "TRX")          # tags on other chains are left out
SOURCE_PREFIX = "graphsense-tagpack:"
_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def read_packs(packs_dir: Path | str) -> list[dict]:
    """Every exchange tag on a traced chain, one dict per (pack, tag), sorted."""
    rows = []
    for path in sorted(Path(packs_dir).glob("*.yaml")):
        pack = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)
        for tag in pack.get("tags") or []:
            def field(name: str) -> str:
                value = tag.get(name, pack.get(name))
                return "" if value is None else str(value).strip()
            if field("category") != "exchange" or field("currency") not in CURRENCIES:
                continue
            rows.append({"address": field("address"), "currency": field("currency"),
                         "actor": field("actor"), "label": field("label"),
                         "category": "exchange", "source": SOURCE_PREFIX + path.stem,
                         "source_url": field("source"), "lastmod": field("lastmod")})
    return _sorted(rows)


def _sorted(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (r["source"], r["currency"], r["address"]))


def write_csv(rows: list[dict], out: Path | str) -> None:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(_sorted(rows))
