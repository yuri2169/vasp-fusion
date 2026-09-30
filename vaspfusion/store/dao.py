"""DuckDB persistence.

DuckDB is a file, not a service. Nothing to install, configure, or have crash
mid-demo on an air-gapped box, and it reads Polars frames directly with no
serialisation step. A graph database would add a service to the deployment for no
analytical benefit at this scale (roadmap §3.4).

Structured columns for anything we filter or sort on; JSON for the nested
payloads (evidence detail, counterfactuals, SHAP rows) that only ever get read
back whole. That keeps the schema small without pretending JSON is a substitute
for indexing.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR PRIMARY KEY, created_at TIMESTAMP, source_file VARCHAR,
    n_rows BIGINT, n_entities BIGINT, n_alerts BIGINT, duration_s DOUBLE,
    receipt JSON, timings JSON, provenance JSON, metrics JSON
);
CREATE TABLE IF NOT EXISTS alerts (
    run_id VARCHAR, rank INTEGER, entity VARCHAR, level VARCHAR,
    score DOUBLE, confidence DOUBLE, interval DOUBLE,
    novelty DOUBLE, supervised DOUBLE, evidence_strength DOUBLE,
    typologies VARCHAR, narrative VARCHAR,
    n_addresses BIGINT, n_tx BIGINT, total_out BIGINT, total_in BIGINT,
    n_ips BIGINT, top_asn BIGINT, top_asn_type VARCHAR, top_country VARCHAR,
    attribution_confidence DOUBLE, attribution_status VARCHAR,
    n_linked_entities BIGINT, linked_entities JSON,
    verdict VARCHAR, verdict_reason VARCHAR, feedback_adjust DOUBLE,
    raised_by VARCHAR, confidence_low DOUBLE, confidence_high DOUBLE,
    confidence_unadjusted DOUBLE
);
CREATE TABLE IF NOT EXISTS evidence (
    run_id VARCHAR, entity VARCHAR, typology VARCHAR, strength DOUBLE,
    summary VARCHAR, txids JSON, detail JSON
);
CREATE TABLE IF NOT EXISTS attributions (
    run_id VARCHAR, entity VARCHAR, rank INTEGER, ip VARCHAR, asn BIGINT,
    asn_org VARCHAR, asn_type VARCHAR, country VARCHAR,
    n_observations BIGINT, n_entities_on_ip BIGINT, p_value DOUBLE, ppmi DOUBLE,
    root_hits BIGINT, root_fraction DOUBLE, infra_penalty DOUBLE,
    timezone_agreement DOUBLE, confidence DOUBLE, interval DOUBLE,
    summary VARCHAR, counterfactuals JSON, status VARCHAR
);
CREATE TABLE IF NOT EXISTS shap_values (
    run_id VARCHAR, entity VARCHAR, feature VARCHAR,
    contribution DOUBLE, value DOUBLE, direction VARCHAR, meaning VARCHAR
);
CREATE TABLE IF NOT EXISTS entity_edges (
    run_id VARCHAR, src VARCHAR, dst VARCHAR, value BIGINT, n_tx BIGINT,
    first_ts TIMESTAMP, last_ts TIMESTAMP
);
CREATE TABLE IF NOT EXISTS entity_txs (
    run_id VARCHAR, entity VARCHAR, txid VARCHAR, ts TIMESTAMP,
    value_out BIGINT, fee BIGINT, n_inputs BIGINT, n_outputs BIGINT,
    output_entropy DOUBLE, peel_ratio DOUBLE, tx_score DOUBLE
);
CREATE TABLE IF NOT EXISTS entity_addresses (
    run_id VARCHAR, entity VARCHAR, address VARCHAR
);
CREATE TABLE IF NOT EXISTS quarantine (
    run_id VARCHAR, reason VARCHAR, n BIGINT, sample JSON
);
CREATE TABLE IF NOT EXISTS behaviour (
    run_id VARCHAR, entity VARCHAR, hour_histogram JSON,
    inferred_offset_min INTEGER, offset_fit DOUBLE, diurnality DOUBLE
);
CREATE TABLE IF NOT EXISTS feedback (
    run_id VARCHAR, entity VARCHAR, verdict VARCHAR, reason VARCHAR, created_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS watchlist (
    address VARCHAR PRIMARY KEY, label VARCHAR, source VARCHAR, added_at TIMESTAMP
);
"""


# Additive only: adding a column is safe against a populated database, dropping
# or retyping one is not. Old rows get NULL and the API reports what it has.
MIGRATIONS = [
    "ALTER TABLE entity_edges ADD COLUMN IF NOT EXISTS first_ts TIMESTAMP",
    "ALTER TABLE entity_edges ADD COLUMN IF NOT EXISTS last_ts TIMESTAMP",
    "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS confidence_low DOUBLE",
    "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS confidence_high DOUBLE",
    "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS confidence_unadjusted DOUBLE",
    "ALTER TABLE feedback ADD COLUMN IF NOT EXISTS analyst VARCHAR",
]


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.path))
        self.con.execute(SCHEMA)
        # `CREATE TABLE IF NOT EXISTS` leaves an existing table alone, so a
        # database written before a column existed keeps the old shape and every
        # read of the new column fails. Additive migrations, run every open.
        for stmt in MIGRATIONS:
            try:
                self.con.execute(stmt)
            except Exception:      # noqa: BLE001 - degrade, never fail (DESIGN.md §1)
                pass

    def close(self) -> None:
        self.con.close()

    # -- writes -----------------------------------------------------------
    def insert_frame(self, table: str, df: pl.DataFrame, run_id: str) -> None:
        if df is None or df.height == 0:
            return
        if "run_id" not in df.columns:
            df = df.with_columns(pl.lit(run_id).alias("run_id"))
        cols = [r[0] for r in self.con.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{table}' ORDER BY ordinal_position").fetchall()]
        keep = [c for c in cols if c in df.columns]
        arrow = df.select(keep).to_arrow()      # noqa: F841 - referenced by DuckDB
        self.con.execute(
            f"INSERT INTO {table} ({', '.join(keep)}) SELECT {', '.join(keep)} FROM arrow")

    def record_run(self, run_id: str, **kw) -> None:
        self.con.execute("DELETE FROM runs WHERE run_id = ?", [run_id])
        self.con.execute(
            "INSERT INTO runs (run_id, created_at, source_file, n_rows, n_entities, "
            "n_alerts, duration_s, receipt, timings, provenance, metrics) "
            "VALUES (?, now(), ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [run_id, kw.get("source_file"), kw.get("n_rows"), kw.get("n_entities"),
             kw.get("n_alerts"), kw.get("duration_s"),
             json.dumps(kw.get("receipt", {})), json.dumps(kw.get("timings", {})),
             json.dumps(kw.get("provenance", {})), json.dumps(kw.get("metrics", {}))])

    def clear_run(self, run_id: str) -> None:
        for t in ("alerts", "evidence", "attributions", "shap_values", "entity_edges",
                  "entity_txs", "entity_addresses", "quarantine", "behaviour"):
            self.con.execute(f"DELETE FROM {t} WHERE run_id = ?", [run_id])

    def set_verdict(self, run_id: str, entity: str, verdict: str, reason: str = "",
                    analyst: str = "unnamed") -> None:
        self.con.execute(
            "INSERT INTO feedback (run_id, entity, verdict, reason, created_at, analyst) "
            "VALUES (?, ?, ?, ?, now(), ?)", [run_id, entity, verdict, reason, analyst])
        self.con.execute(
            "UPDATE alerts SET verdict = ?, verdict_reason = ? "
            "WHERE run_id = ? AND entity = ?", [verdict, reason, run_id, entity])

    def add_watchlist(self, rows: list[tuple[str, str]], source: str) -> None:
        if not rows:
            return
        self.con.executemany(
            "INSERT INTO watchlist (address, label, source, added_at) VALUES (?, ?, ?, now()) "
            "ON CONFLICT (address) DO UPDATE SET label = excluded.label, source = excluded.source",
            [(a, lab, source) for a, lab in rows])

    # -- reads ------------------------------------------------------------
    def q(self, sql: str, params: list | None = None) -> list[dict]:
        cur = self.con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def latest_run(self) -> dict | None:
        rows = self.q("SELECT * FROM runs ORDER BY created_at DESC LIMIT 1")
        return rows[0] if rows else None

    def runs(self) -> list[dict]:
        return self.q("SELECT run_id, created_at, source_file, n_rows, n_entities, "
                      "n_alerts, duration_s FROM runs ORDER BY created_at DESC")
