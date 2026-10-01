"""Build data/labels.duckdb from the research label CSVs.

Inputs (both real, both in ../research/data):
  * wallet-attribution/data/<chain>.csv - 115k labelled addresses, MIT. `_all.csv`
    is the concatenation of the per-chain files and is skipped, or every row
    would be counted twice.
  * indian_vasps_dune_spellbook.csv - CoinDCX, WazirX and CoinSwitch addresses.

  * data/derived/<chain>.csv (optional) - deposit addresses derived by B4's discovery
    rules (`make discover`). Only rows with status `derived` are loaded, as tier
    `derived`, each with its rule confidence and evidence text.

One row per (address, chain). When sources disagree the highest tier wins, then
the higher-priority category, then the source name - a total order, so the build
is deterministic and a rebuild is byte-for-byte the same table. `derived` is the
lowest tier, so a derived row never replaces a label from any other source.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

import duckdb
import polars as pl

from .normalize import (
    address_chain,
    CATEGORY_RANK, DERIVED_SOURCE, TIER_RANK, canonical_entity, infer_kind, map_category,
    normalize_address, normalize_chain, tier_for,
)

LABEL_COLUMNS = ["address", "chain", "entity", "category", "kind", "tier", "source",
                 "source_url", "label", "confidence", "evidence"]
_RULE_WORDS = {"sweep+gas": "sweep + gas payer", "sweep+station": "sweep + gas station",
               "sweep": "sweep"}
DUNE_SOURCE_URL = "https://github.com/duneanalytics/spellbook"

_DDL = """
CREATE TABLE labels (
    address    VARCHAR NOT NULL,
    chain      VARCHAR NOT NULL,
    entity     VARCHAR NOT NULL,
    category   VARCHAR NOT NULL,
    kind       VARCHAR NOT NULL,
    tier       VARCHAR NOT NULL,
    source     VARCHAR NOT NULL,
    source_url VARCHAR,
    label      VARCHAR,
    confidence DOUBLE,   -- derived rows only: rule confidence, not calibrated
    evidence   VARCHAR,  -- derived rows only: what the rules saw
    PRIMARY KEY (address, chain)
)
"""


def _row(address: str, chain_raw: str, entity_raw: str, label: str, category_raw: str,
         source: str, source_url: str) -> dict:
    chain = normalize_chain(chain_raw)
    entity = canonical_entity(entity_raw, label)
    category = map_category(category_raw, entity, label, entity_raw)
    return {
        "address": normalize_address(address, chain),
        "chain": chain,
        "entity": entity,
        "category": category,
        "kind": infer_kind(label, source),
        "tier": tier_for(source),
        "source": source,
        "source_url": source_url,
        "label": label,
        "confidence": None,
        "evidence": None,
        # Upstream said `entity`; Etherscan's Exchange tag made it an exchange.
        "_promoted": category_raw.strip().lower() == "entity" and category == "exchange",
    }


def _read(path: Path) -> list[dict]:
    return pl.read_csv(path, infer_schema=False).fill_null("").to_dicts()


def read_wallet_attribution(data_dir: Path) -> list[dict]:
    rows = []
    for path in sorted(Path(data_dir).glob("*.csv")):
        if path.name.startswith("_"):
            continue
        for r in _read(path):
            rows.append(_row(r["address"], r["network"], r["entity"], r["label"],
                             r["category"], r["source"], r["source_url"]))
    return rows


def read_dune(csv_path: Path) -> list[dict]:
    # Every row in this extract is a VASP wallet (the file lists exchanges only).
    return [_row(r["address"], r["chain"], r["exchange"], r["name_tag"], "exchange",
                 r["source"], DUNE_SOURCE_URL) for r in _read(Path(csv_path))]


def read_derived(derived_dir: Path | None) -> list[dict]:
    """The `derived` rows of every discovery CSV in the folder (conflicts and addresses
    that were already labelled are in those files too, and are not labels)."""
    rows = []
    if derived_dir is None or not Path(derived_dir).is_dir():
        return rows
    for path in sorted(Path(derived_dir).glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["status"] != "derived":
                    continue
                chain = normalize_chain(r["chain"])
                rows.append({
                    "address": normalize_address(r["address"], chain), "chain": chain,
                    "entity": r["entity"], "category": r["category"], "kind": r["kind"],
                    "tier": "derived", "source": DERIVED_SOURCE, "source_url": None,
                    "label": f"{r['entity']} deposit address "
                             f"(derived: {_RULE_WORDS[r['rule']]})",
                    "confidence": float(r["confidence"]), "evidence": r["evidence"],
                    "_promoted": False,
                })
    return rows


def _validate(rows: list[dict]) -> tuple[list[dict], int, int]:
    """Drop rows whose address is valid on no chain; re-file misfiled ones.
    Returns (kept rows, dropped count, re-filed count)."""
    kept, dropped, refiled = [], 0, 0
    for r in rows:
        chain = address_chain(r["address"], r["chain"])
        if chain is None:
            dropped += 1
            continue
        if chain != r["chain"]:
            refiled += 1
            r = {**r, "address": normalize_address(r["address"], chain), "chain": chain,
                 "label": f"{r['label']} [filed upstream as {r['chain']}]"}
        kept.append(r)
    return kept, dropped, refiled


def _dedupe(rows: list[dict]) -> pl.DataFrame:
    df = pl.DataFrame(rows, schema={**{c: pl.String for c in LABEL_COLUMNS},
                                    "confidence": pl.Float64, "_promoted": pl.Boolean})
    df = df.with_columns(
        pl.col("tier").replace_strict(TIER_RANK).alias("_tr"),
        pl.col("category").replace_strict(CATEGORY_RANK).alias("_cr"),
    )
    # the last two keys only matter between derived rows of two discovery runs:
    # the more confident one wins
    df = df.sort(["address", "chain", "_tr", "_cr", "source", "confidence", "evidence"],
                 descending=[False, False, True, True, False, True, False], nulls_last=True)
    return df.unique(subset=["address", "chain"], keep="first", maintain_order=True) \
             .select([*LABEL_COLUMNS, "_promoted"])


def label_stats(con: duckdb.DuckDBPyConnection) -> dict:
    def by(col: str) -> dict:
        return dict(con.execute(f"SELECT {col}, count(*) FROM labels GROUP BY 1 "
                                "ORDER BY 2 DESC, 1").fetchall())
    return {"total": con.execute("SELECT count(*) FROM labels").fetchone()[0],
            "by_chain": by("chain"), "by_category": by("category"),
            "by_tier": by("tier"), "by_kind": by("kind")}


def build_labels(db_path: Path, wa_dir: Path, dune_csv: Path,
                 derived_dir: Path | None = None) -> dict:
    derived = read_derived(derived_dir)
    rows = read_wallet_attribution(wa_dir) + read_dune(dune_csv) + derived
    kept, dropped, refiled = _validate(rows)
    df = _dedupe(kept)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_name(db_path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    with duckdb.connect(str(tmp)) as con:
        con.execute(_DDL)
        con.register("df", df.to_arrow())
        con.execute(f"INSERT INTO labels SELECT {', '.join(LABEL_COLUMNS)} FROM df")
        con.unregister("df")
        stats = label_stats(con)
    os.replace(tmp, db_path)  # readers never see a half-built DB
    stats["raw_rows"] = len(rows) - len(derived)
    stats["derived_loaded"] = len(derived)
    # derived rows that lost to a label of a higher tier for the same address
    stats["derived_shadowed"] = len(derived) - stats["by_tier"].get("derived", 0)
    stats["invalid_dropped"] = dropped
    stats["chain_refiled"] = refiled
    stats["duplicates_dropped"] = len(kept) - stats["total"] - stats["derived_shadowed"]
    stats["exchange_tag_promoted"] = int(df["_promoted"].sum())
    return stats
