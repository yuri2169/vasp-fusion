"""Build data/labels.duckdb from the research label CSVs.

Inputs (both real, both in ../research/data):
  * wallet-attribution/data/<chain>.csv - 115k labelled addresses, MIT. `_all.csv`
    is the concatenation of the per-chain files and is skipped, or every row
    would be counted twice.
  * indian_vasps_dune_spellbook.csv - CoinDCX, WazirX and CoinSwitch addresses.

  * graphsense_tagpacks_exchange.csv (optional) - the exchange packs of the GraphSense
    TagPacks (MIT), flattened by `cli tagpacks` (labels/tagpacks.py): BTC, ETH and TRX
    addresses of exchanges, among them WalletExplorer's named exchange wallets.

  * data/threat_tags.csv (optional) - threat tags flattened by `cli threats`
    (labels/threats.py) from the OFAC SDN XML, Ransomwhere and GraphSense TagPacks. A tag
    is joined onto the label of its address as the `threat_*` columns; a tagged address
    that nothing else labels gets a row of its own. Rows filed as `scam` are tagged fraud.

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
    normalize_address, normalize_chain, tagpack_entity, tier_for,
)

THREAT_COLUMNS = ["threat", "threat_entity", "threat_source", "threat_url", "threat_evidence"]
LABEL_COLUMNS = ["address", "chain", "entity", "category", "kind", "tier", "source",
                 "source_url", "label", "confidence", "evidence", "confidence_low",
                 "confidence_high", "model", *THREAT_COLUMNS]
_DERIVED_COLUMNS = {"address", "chain", "entity", "category", "kind", "status", "rule",
                    "confidence", "evidence"}
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
    confidence DOUBLE,   -- derived rows only: the model's (B6) where it scored the address,
                         -- else the discovery rules' hand-set confidence
    evidence   VARCHAR,  -- derived rows only: what the rules saw (and the model said)
    confidence_low  DOUBLE,  -- model-scored rows only: the calibrated range
    confidence_high DOUBLE,
    model      VARCHAR,  -- rows the model scored: JSON {p, low, high, basis, reasons}
    threat          VARCHAR,  -- tagged addresses only: ransomware, darknet_market,
                              -- terrorism_financing, fraud or sanctioned_other
    threat_entity   VARCHAR,  -- who the source names (a ransomware family, a listed entity)
    threat_source   VARCHAR,  -- the source of the tag (may differ from the label's source)
    threat_url      VARCHAR,
    threat_evidence VARCHAR,  -- the source's own words: programme codes, pack fields
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
        "confidence_low": None,
        "confidence_high": None,
        "model": None,
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


def read_tagpacks(csv_path: Path | None) -> list[dict]:
    """The exchange tags of the GraphSense TagPacks, from the CSV `cli tagpacks` writes
    (labels/tagpacks.py). No file, no rows: the source is optional."""
    if csv_path is None or not Path(csv_path).is_file():
        return []
    rows = []
    for r in _read(Path(csv_path)):
        row = _row(r["address"], r["currency"], tagpack_entity(r["actor"], r["label"]),
                   r["label"], r["category"], r["source"], r["source_url"])
        # BitMEX's published list ("bitmex reserve wallet") is every address it holds
        # coins at, one per customer: deposit addresses, not a handful of reserve wallets
        if r["source"].startswith("graphsense-tagpack:exchange-wallets-bitmex"):
            row["kind"] = "deposit"
        rows.append(row)
    return rows


def read_model_scores(model_dir: Path | None) -> dict[tuple[str, str], dict]:
    """`<model_dir>/<chain>/scores.csv` (written by `make model`): the deposit-address
    model's confidence, range, reasons and evidence text per derived address."""
    scores: dict[tuple[str, str], dict] = {}
    if model_dir is None or not Path(model_dir).is_dir():
        return scores
    for path in sorted(Path(model_dir).glob("*/scores.csv")):
        with path.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                chain = normalize_chain(r["chain"])
                scores[(normalize_address(r["address"], chain), chain)] = r
    return scores


def _number(score: dict | None, key: str) -> float | None:
    return float(score[key]) if score and score.get(key) not in (None, "") else None


def read_derived(derived_dir: Path | None, model_dir: Path | None = None) -> list[dict]:
    """The `derived` rows of every discovery CSV in the folder (conflicts and addresses
    that were already labelled are in those files too, and are not labels). Where the
    model scored an address for the same exchange, the score file's confidence, range,
    reasons and evidence are used (classify/score.py decides them: the model's value
    when it confirms the label, the rules' confidence when it does not)."""
    rows = []
    if derived_dir is None or not Path(derived_dir).is_dir():
        return rows
    scores = read_model_scores(model_dir)
    for path in sorted(Path(derived_dir).glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if not _DERIVED_COLUMNS <= set(reader.fieldnames or ()):
                continue                    # some other CSV, not a discovery file
            for r in reader:
                if r["status"] != "derived":
                    continue
                confidence = float(r["confidence"])
                if not 0 < confidence <= 1:
                    raise ValueError(f"{path.name}: {r['address']} has confidence "
                                     f"{r['confidence']}; a derived label needs one in (0, 1]")
                chain = normalize_chain(r["chain"])
                address = normalize_address(r["address"], chain)
                score = scores.get((address, chain))
                if score is not None and score["entity"] != r["entity"]:
                    score = None            # scored as another exchange's: not this label's
                rows.append({
                    "address": address, "chain": chain,
                    "entity": r["entity"], "category": r["category"], "kind": r["kind"],
                    "tier": "derived", "source": DERIVED_SOURCE, "source_url": None,
                    "label": f"{r['entity']} deposit address "
                             f"(derived: {_RULE_WORDS[r['rule']]})",
                    "confidence": float(score["confidence"]) if score else confidence,
                    "evidence": score["evidence"] if score else r["evidence"],
                    # empty when the model did not confirm the label: rule confidence kept
                    "confidence_low": _number(score, "confidence_low"),
                    "confidence_high": _number(score, "confidence_high"),
                    "model": score["model"] if score else None,
                    "_promoted": False,
                })
    return rows


def _drop_conflicting(derived: list[dict]) -> tuple[list[dict], int]:
    """Two discovery runs that name different exchanges for one address disagree, and
    neither is loaded: a conflict is reported, never settled by picking a side."""
    named: dict[tuple[str, str], set[str]] = {}
    for r in derived:
        named.setdefault((r["address"], r["chain"]), set()).add(r["entity"])
    kept = [r for r in derived if len(named[(r["address"], r["chain"])]) == 1]
    return kept, len(derived) - len(kept)


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
                                    "confidence": pl.Float64, "confidence_low": pl.Float64,
                                    "confidence_high": pl.Float64, "_promoted": pl.Boolean})
    df = df.with_columns(
        pl.col("tier").replace_strict(TIER_RANK).alias("_tr"),
        pl.col("category").replace_strict(CATEGORY_RANK).alias("_cr"),
    )
    # the last two keys only matter between derived rows of two discovery runs:
    # the more confident one wins
    df = df.sort(["address", "chain", "_tr", "_cr", "source", "confidence", "evidence"],
                 descending=[False, False, True, True, False, True, False], nulls_last=True)
    return df.unique(subset=["address", "chain"], keep="first", maintain_order=True) \
             .select([*LABEL_COLUMNS, "_promoted"])    # the threat columns are still empty


def _threat_category(row: dict) -> str:
    """The category of a label row made for a tagged address nothing else labels. No
    category is invented: a listed address is `sanctioned`, a fraud address is `scam`
    (as the scam lists already file them), anything else is a named `entity`."""
    if row["source"] == OFAC_SOURCE:
        return "sanctioned"
    return "scam" if row["threat"] == "fraud" else "entity"


def _apply_threats(df: pl.DataFrame, tags: list[dict]) -> tuple[pl.DataFrame, dict]:
    """Join the threat tags onto the deduplicated label table. Returns the table with the
    `threat_*` columns filled, and what was done (counts)."""
    empty = {c: pl.String for c in ("address", "chain", *THREAT_COLUMNS)}
    tdf = pl.DataFrame([{"address": t["address"], "chain": t["chain"], "threat": t["threat"],
                         "threat_entity": t["entity"], "threat_source": t["source"],
                         "threat_url": t["source_url"] or None,
                         "threat_evidence": t["evidence"]} for t in tags], schema=empty)
    df = df.drop(THREAT_COLUMNS).join(tdf, on=["address", "chain"], how="left")
    joined = int(df["threat"].is_not_null().sum())

    have = set(zip(df["address"].to_list(), df["chain"].to_list()))
    fresh = [{"address": t["address"], "chain": t["chain"], "entity": t["entity"],
              "category": _threat_category(t), "kind": "unknown", "tier": tier_for(t["source"]),
              "source": t["source"], "source_url": t["source_url"] or None,
              "label": t["entity"], "confidence": None, "evidence": None,
              "confidence_low": None, "confidence_high": None, "model": None,
              "threat": t["threat"], "threat_entity": t["entity"], "threat_source": t["source"],
              "threat_url": t["source_url"] or None, "threat_evidence": t["evidence"],
              "_promoted": False}
             for t in tags if (t["address"], t["chain"]) not in have]
    if fresh:
        df = pl.concat([df, pl.DataFrame(fresh, schema=df.schema).select(df.columns)])

    # The scam lists already in the store (MyEtherWallet's, explorer tags) are fraud
    # reports in their own words: the tag restates them, it adds no claim.
    scam = (pl.col("category") == "scam") & pl.col("threat").is_null()
    retagged = int(df.select(scam.sum()).item())
    df = df.with_columns(
        pl.when(scam).then(pl.lit("fraud")).otherwise(pl.col("threat")).alias("threat"),
        pl.when(scam).then(pl.col("entity")).otherwise(pl.col("threat_entity"))
          .alias("threat_entity"),
        pl.when(scam).then(pl.col("source")).otherwise(pl.col("threat_source"))
          .alias("threat_source"),
        pl.when(scam).then(pl.col("source_url")).otherwise(pl.col("threat_url"))
          .alias("threat_url"),
        pl.when(scam).then(pl.format("Filed as a scam address by {}: {}", pl.col("source"),
                                     pl.col("label").fill_null(pl.col("entity"))))
          .otherwise(pl.col("threat_evidence")).alias("threat_evidence"))
    unlisted = int(df.select(((pl.col("category") == "sanctioned")
                              & pl.col("threat").is_null()).sum()).item())
    return df.sort(["address", "chain"]), {
        "threat_rows": len(tags), "threat_joined": joined, "threat_new_rows": len(fresh),
        "scam_retagged": retagged, "sanctioned_without_programme": unlisted}


def threat_stats(con: duckdb.DuckDBPyConnection) -> dict:
    """Tagged labels per threat, per (threat, chain) and per (threat, source)."""
    out: dict = {"by_threat": {}, "threat_by_chain": {}, "threat_by_source": {}}
    have = {r[0] for r in con.execute("DESCRIBE labels").fetchall()}
    if "threat" not in have:
        return out
    out["by_threat"] = dict(con.execute(
        "SELECT threat, count(*) FROM labels WHERE threat IS NOT NULL GROUP BY 1 "
        "ORDER BY 2 DESC, 1").fetchall())
    for threat, chain, n in con.execute(
            "SELECT threat, chain, count(*) FROM labels WHERE threat IS NOT NULL "
            "GROUP BY 1, 2 ORDER BY 1, 3 DESC, 2").fetchall():
        out["threat_by_chain"].setdefault(threat, {})[chain] = n
    for threat, source, n in con.execute(
            "SELECT threat, threat_source, count(*) FROM labels WHERE threat IS NOT NULL "
            "GROUP BY 1, 2").fetchall():
        fam = source_family(family(source))
        d = out["threat_by_source"].setdefault(threat, {})
        d[fam] = d.get(fam, 0) + n
    for threat, d in out["threat_by_source"].items():
        out["threat_by_source"][threat] = dict(sorted(d.items(), key=lambda kv: (-kv[1], kv[0])))
    return out


from .sources import by_source, family  # noqa: E402
from .threats import OFAC_SOURCE, read_csv as read_threat_tags, source_family  # noqa: E402


def label_stats(con: duckdb.DuckDBPyConnection) -> dict:
    def by(col: str) -> dict:
        return dict(con.execute(f"SELECT {col}, count(*) FROM labels GROUP BY 1 "
                                "ORDER BY 2 DESC, 1").fetchall())
    return {"total": con.execute("SELECT count(*) FROM labels").fetchone()[0],
            "by_chain": by("chain"), "by_category": by("category"),
            "by_tier": by("tier"), "by_kind": by("kind"), **threat_stats(con),
            "by_source": by_source(con.execute(
                "SELECT source, tier, count(*) FROM labels GROUP BY 1, 2").fetchall())}


RECORDED_LABELS = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "demo" / "labels.json"


def missing_sources(wa_dir: Path, dune_csv: Path) -> list[str]:
    """The label sources `build_labels` cannot do without and that are not there."""
    missing = []
    if not any(Path(wa_dir).glob("*.csv")):
        missing.append(f"{wa_dir}/*.csv (the wallet-attribution set, one CSV per chain)")
    if not Path(dune_csv).is_file():
        missing.append(f"{dune_csv} (the Dune spellbook extract of Indian exchanges)")
    return missing


def build_recorded_labels(db_path: Path, json_path: Path = RECORDED_LABELS) -> dict:
    """A label database holding only the rows the recorded demo wallets' traces read.

    The full database is built from label sets that are not part of this repository.
    What is tracked is every row of it that the thirteen recorded traces (and the two
    watchlist traces) were answered with, kept as they were returned
    (tests/fixtures/demo/labels.json). A database of just those rows gives the same
    answer for those wallets: the same findings fingerprints, checked by
    `cli demo --golden`. It is not a label store for anything else: a wallet that was
    not recorded meets almost no label here."""
    import json
    from ..labels.lookup import Label
    rows = json.loads(Path(json_path).read_text())["labels"].values()
    labels = [Label.from_dict(r) for r in rows]        # rows of any vintage, model as JSON
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_name(db_path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    with duckdb.connect(str(tmp)) as con:
        con.execute(_DDL)
        con.executemany(f"INSERT INTO labels VALUES ({', '.join('?' * len(LABEL_COLUMNS))})",
                        [[getattr(lab, c) for c in LABEL_COLUMNS] for lab in labels])
        stats = label_stats(con)
    tmp.replace(db_path)
    return stats


def build_labels(db_path: Path, wa_dir: Path, dune_csv: Path,
                 derived_dir: Path | None = None, model_dir: Path | None = None,
                 tagpacks_csv: Path | None = None, threats_csv: Path | None = None) -> dict:
    read = read_derived(derived_dir, model_dir)
    derived, conflicting = _drop_conflicting(read)
    derived, dropped_derived, _ = _validate(derived)
    tagpacks = read_tagpacks(tagpacks_csv)
    rows = read_wallet_attribution(wa_dir) + read_dune(dune_csv) + tagpacks
    kept, dropped, refiled = _validate(rows)
    df, threat_counts = _apply_threats(_dedupe(kept + derived), read_threat_tags(threats_csv))
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
        stats["derived_exchange"] = con.execute(
            "SELECT count(*) FROM labels WHERE tier = 'derived' AND category = 'exchange'"
        ).fetchone()[0]
        stats["derived_model_scored"] = con.execute(
            "SELECT count(*) FROM labels WHERE confidence_low IS NOT NULL").fetchone()[0]
        stats["tagpack_kept"] = con.execute(
            "SELECT count(*) FROM labels WHERE source LIKE 'graphsense-tagpack:%' "
            "AND threat_source IS DISTINCT FROM source").fetchone()[0]   # exchange packs only
        stats["derived_model_unconfirmed"] = con.execute(
            "SELECT count(*) FROM labels WHERE model IS NOT NULL AND confidence_low IS NULL"
        ).fetchone()[0]
    os.replace(tmp, db_path)  # readers never see a half-built DB
    stats.update(threat_counts)
    stats["raw_rows"] = len(rows)
    stats["tagpack_rows"] = len(tagpacks)
    stats["derived_loaded"] = len(read)
    stats["derived_conflicting"] = conflicting
    # derived rows that lost to a label of a higher tier, or that two runs both named
    stats["derived_shadowed"] = len(derived) - stats["by_tier"].get("derived", 0)
    stats["invalid_dropped"] = dropped + dropped_derived
    stats["chain_refiled"] = refiled
    stats["duplicates_dropped"] = len(kept) + len(derived) - stats["total"] \
        - stats["derived_shadowed"] + stats["threat_new_rows"]
    stats["exchange_tag_promoted"] = int(df["_promoted"].sum())
    return stats
