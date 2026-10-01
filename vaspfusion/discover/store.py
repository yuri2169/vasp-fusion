"""Where a discovery run is kept: `data/derived/<chain>.csv` (one row per address the
sweep rule fired on, conflicts included) and `<chain>_report.json` (config, stats
per exchange, gas stations). `make labels` reads the CSVs and adds the rows with
status `derived` to the label DB as tier `derived`; nothing else in them is a label.
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, fields
from pathlib import Path

from .crawl import DiscoveryResult, Finding

NOTE = ("Derived by the sweep and gas-payer rules from labelled exchange wallets. "
        "Confidences are rule-based, not calibrated.")
_INT = {"n_deposits", "n_senders", "n_sweeps", "n_paid"}
_FLOAT = {"confidence", "share", "median_delay_s"}
_OPTIONAL = {"confidence", "conflict", "median_delay_s", "gas_payer", "gas_payer_entity"}
COLUMNS = [f.name for f in fields(Finding)]


def write_result(out_dir: Path | str, result: DiscoveryResult) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{result.chain}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(COLUMNS)
        for f in result.findings:
            row = asdict(f)
            w.writerow(["" if row[c] is None else row[c] for c in COLUMNS])
    report_path = out_dir / f"{result.chain}_report.json"
    report = {"chain": result.chain, "note": NOTE, "config": result.config,
              "totals": result.totals, "stats": result.stats, "stations": result.stations}
    report_path.write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + "\n")
    return csv_path, report_path


def _value(name: str, text: str):
    if text == "" and name in _OPTIONAL:
        return None
    if name in _INT:
        return int(text)
    if name in _FLOAT:
        return float(text)
    if name == "complete":
        return text == "True"
    return text


def read_findings(csv_path: Path | str) -> list[Finding]:
    with Path(csv_path).open(newline="", encoding="utf-8") as fh:
        return [Finding(**{k: _value(k, v) for k, v in row.items()})
                for row in csv.DictReader(fh)]
