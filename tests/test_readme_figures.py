"""The judges' section of the README quotes its figures from tracked artefacts. Each figure is
rebuilt here from the artefact and must appear in that section as written, so a re-measured
artefact or a hand-edited figure that no longer matches fails."""
import json
from pathlib import Path

import pytest
import yaml

from vaspfusion import coverage
from vaspfusion.api import main

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
JUDGES = README.split("## For judges", 1)[1].split("\n## ", 1)[0]
CHAIN_NAMES = {"tron": "Tron", "ethereum": "Ethereum", "bitcoin": "Bitcoin", "bsc": "BNB Chain",
               "polygon": "Polygon", "solana": "Solana"}


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text())


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%"


def _benchmark_rows() -> list[dict]:
    return [c for c in _load("artifacts/benchmark_v1/summary.json")["chains"] if c["measured"]]


@pytest.mark.parametrize("row", _benchmark_rows(), ids=lambda c: c["chain"])
def test_the_six_chain_table_row_is_the_benchmark(row):
    expected = (
        f"| {CHAIN_NAMES[row['chain']]} | {row['wallets']} | {row['named']} | "
        f"{row['wrong']} of {row['named']} ({_pct(row['wrong'], row['named'])}; at most {100 * row['error_upper_95']:.1f}%) | "
        f"{row['not_named']} | {row['baseline_named']} | "
        f"{row['baseline_wrong']} of {row['baseline_named']} "
        f"({_pct(row['baseline_wrong'], row['baseline_named'])}; at most {100 * row['baseline_error_upper_95']:.1f}%) |"
    )
    assert expected in JUDGES


def test_the_risk_figure_is_the_fresh_set_with_own_label_hidden():
    results = _load("artifacts/risk_validation_v2/results.json")
    arms = results["views"][results["main_view"]]["arms"]
    pos, ctl = arms["positive"], arms["control"]
    assert f"{pos['high_or_above']} of {pos['wallets']}" in JUDGES
    assert f"{ctl['high_or_above']} of {ctl['wallets']}" in JUDGES


def test_the_documented_case_reaches_no_exchange_from_any_tagged_wallet():
    table = _load("artifacts/wazirx_2024/trace_table.json")
    assert f"{table['addresses']} wallets" in JUDGES
    for view in ("as_shown", "entity_hidden"):
        assert not any(r[view]["outcome"] == "ATTRIBUTED" for r in table["rows"])
    hidden = table["summary"]["entity_hidden"]
    mixer = hidden["reached a mixer or a sanctioned address"]
    assert f"{mixer} reach Tornado Cash" in JUDGES


def test_the_indian_list_count_is_the_official_list():
    providers = yaml.safe_load((ROOT / "data" / "indian_exchanges.yaml").read_text())["providers"]
    assert f"{len(providers)} providers" in JUDGES


def test_the_coverage_counts_are_the_coverage_page():
    counts = coverage.build(main.TRACEABLE)["counts"]
    assert (f"{counts['built']} lines built, {counts['ready_to_connect']} ready to connect, "
            f"{counts['partly']} partly built, {counts['planned']} only planned") in JUDGES


def test_the_freeze_list_count_is_the_snapshot():
    frozen = _load("data/usdt_frozen.json")
    assert f"{frozen['total']:,} addresses" in JUDGES
    assert f"Tron {frozen['counts']['tron']:,}, Ethereum {frozen['counts']['ethereum']:,}" in JUDGES
    check = frozen["check"]
    assert f"{check['agreed']} of {check['checked']}" in JUDGES
