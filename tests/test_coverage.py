"""The coverage page is held to the truth: every row quotes the problem statement, every
line of the problem statement has a row, and a row that says "built" points at a screen
that exists and at a test or a make target that exists."""
import re
from pathlib import Path

import pytest

from vaspfusion import coverage
from vaspfusion.api import main

ROOT = Path(__file__).resolve().parents[1]
PS = (ROOT / "docs" / "problem_statement.md").read_text()
ROWS = coverage.build(main.TRACEABLE)["rows"]


def _flat(text: str) -> str:
    """Words only: list markers, line breaks and punctuation spacing do not matter."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _ui_routes() -> set[str]:
    app = (ROOT / "ui" / "src" / "App.tsx").read_text()
    return {"/"} | {"/" + p for p in re.findall(r'path="([^"*]+)"', app)}


def _make_targets() -> set[str]:
    return set(re.findall(r"^([a-z][a-z-]*):", (ROOT / "Makefile").read_text(), re.M))


@pytest.mark.parametrize("row", ROWS, ids=lambda r: r["id"])
def test_every_row_quotes_the_problem_statement(row):
    assert _flat(row["text"]) in _flat(PS)


def test_every_line_of_the_problem_statement_has_a_row():
    quoted = " | ".join(_flat(r["text"]) for r in ROWS)
    body = PS.split("## Description", 1)[1]
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        assert _flat(line) in quoted, f"no coverage row quotes: {line}"
    for phrase in ("visualization of fund movement", "cross-chain transaction mapping",
                   "risk scoring", "identification of laundering typologies",
                   "reduce investigation time", "improve asset freezing efficiency",
                   "enhance attribution capabilities",
                   "strengthen cross-border cybercrime investigations involving VDAs"):
        assert _flat(phrase) in quoted


@pytest.mark.parametrize("row", ROWS, ids=lambda r: r["id"])
def test_a_row_says_what_exists_and_what_is_missing(row):
    assert row["status"] in coverage.STATUSES
    assert row["what"].strip()
    if row["status"] != "built":
        assert row["gap"] and len(row["gap"]) > 20, "a row that is not built says what is missing"
    for text in (row["what"], row["gap"] or ""):
        assert not re.search(r"\b[A-Z]{4,}\b$", text.strip()), "a placeholder was left in"


@pytest.mark.parametrize("row", ROWS, ids=lambda r: r["id"])
def test_the_screen_of_every_row_exists(row):
    assert row["where"] in _ui_routes()


@pytest.mark.parametrize("row", [r for r in ROWS if r["status"] == "built"],
                         ids=lambda r: r["id"])
def test_the_evidence_of_every_built_row_exists(row):
    if row["evidence_kind"] == "make":
        assert row["evidence"] in _make_targets()
        return
    file, _, name = row["evidence"].partition("::")
    path = ROOT / file
    assert path.is_file(), f"{file} does not exist"
    if name:
        assert re.search(rf"^def {re.escape(name)}\(", path.read_text(), re.M), \
            f"{file} has no test called {name}"


def test_the_chain_rows_follow_the_chains_that_trace():
    row = {"named_chains": ["bitcoin", "ethereum", "tron", "bsc", "solana", "polygon"]}
    some = coverage._chain_row(row, ("tron", "ethereum", "polygon", "bitcoin", "base"))
    assert some["status"] == "partly"
    assert "BNB Chain and Solana cannot be traced yet" in some["gap"]
    assert "Base" in some["what"] and "Solana" not in some["what"]
    every = coverage._chain_row(row, ("tron", "ethereum", "polygon", "bitcoin", "bsc", "solana"))
    assert every == {"status": "built", "gap": None, "what": every["what"]}
    assert coverage._chain_row(row, ())["status"] == "planned"
    live = [r for r in ROWS if r["computed"]]
    assert len(live) == 2
    for r in live:
        missing = [c for c in ("bsc", "solana") if c not in main.TRACEABLE]
        assert r["status"] == ("partly" if missing else "built")


def test_the_counts_add_up():
    page = coverage.build(main.TRACEABLE)
    assert sum(page["counts"].values()) == page["total"] == len(ROWS) == 24


def test_a_row_that_is_not_built_must_say_why(tmp_path):
    bad = tmp_path / "c.yaml"
    bad.write_text("rows:\n  - {id: a, section: s, text: t, status: partly, what: w, "
                   "where: /cases, evidence: {make: demo}}\n")
    with pytest.raises(coverage.CoverageError, match="does not say what is missing"):
        coverage.load(bad)
