"""The demo runbook points at files, make targets and recorded cases. Each must exist, and the
table of recorded wallets must be the demo set, so a renamed file or a fourteenth case shows."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = (ROOT / "docs" / "demo_runbook.md").read_text()
CODE = re.findall(r"`([^`]+)`", RUNBOOK)
DEMO_IDS = {c["id"] for c in json.loads((ROOT / "demo" / "cases.json").read_text())["cases"]}


def _paths() -> list[str]:
    return sorted({c for c in CODE if "/" in c and " " not in c and not c.startswith(("/", "http", "POST", "GET"))})


@pytest.mark.parametrize("path", _paths())
def test_every_file_the_runbook_names_exists(path):
    assert (ROOT / path).exists(), path


def test_every_make_target_the_runbook_names_exists():
    targets = set(re.findall(r"^([a-z][a-z-]*):", (ROOT / "Makefile").read_text(), re.M))
    named = {t for c in CODE for t in re.findall(r"\bmake ([a-z][a-z-]*)", c)}
    assert named and named <= targets, named - targets


def test_the_recorded_wallets_table_is_the_demo_set():
    section = RUNBOOK.split("**Recorded (always work", 1)[1].split("**Live:**", 1)[0]
    listed = set(re.findall(r"^\| `([a-z0-9-]+)` \|", section, re.M))
    assert listed == DEMO_IDS
