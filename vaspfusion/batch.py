"""Batch intake: many wallets in one upload, and one result table out.

This module is the part that needs no web framework: reading the rows of a CSV, what a
finished case contributes to the result table, the counts, and the table as CSV. The
routes are in api/main.py; the rows and the cases are in the case store.

A bad row never stops a batch. It is kept, with the reason it was refused and the row
number it had in the upload, so the officer can fix that row and send it again.
"""
from __future__ import annotations

import csv
import io

MAX_ROWS = 2000                 # per upload; a larger list is sent as several batches
MAX_CSV_BYTES = 2_000_000
_ADDRESS = ("address", "wallet", "wallet address", "wallet_address")
_CHAIN = ("chain", "network", "blockchain")
_REF = ("case_ref", "case ref", "case reference", "reference", "ref", "fir")
RESULT_COLUMNS = ("row", "wallet", "chain", "case_reference", "status", "outcome",
                  "named_exchange", "hops", "proximity_rank", "share_of_funds", "confidence",
                  "risk_class", "budget_ended_trace", "case", "error")


class BatchError(ValueError):
    """An upload that cannot be read as a list of wallets at all."""


def parse_csv(text: str) -> list[dict]:
    """Rows of an uploaded CSV as {row, address, chain, case_ref}. `row` is the line's
    number in the file, counting a header line, so it matches what a spreadsheet shows.

    With a header line the columns are found by name (address or wallet; chain; case_ref
    or reference), in any order. Without one they are taken in that order. Blank lines
    are skipped. Commas, semicolons and tabs are all accepted as separators."""
    if len(text.encode()) > MAX_CSV_BYTES:
        raise BatchError(f"The file is larger than {MAX_CSV_BYTES // 1_000_000} MB. "
                         "Split it into smaller files.")
    text = text.lstrip("﻿")
    first = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = max(",;\t", key=first.count) if any(c in first for c in ",;\t") else ","
    lines = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    cols = {"address": 0, "chain": 1, "case_ref": 2}
    header_at = None
    for i, line in enumerate(lines):
        cells = [c.strip().lower() for c in line]
        if not any(cells):
            continue
        if any(c in _ADDRESS for c in cells):
            header_at = i
            cols = {"address": next(k for k, c in enumerate(cells) if c in _ADDRESS),
                    "chain": next((k for k, c in enumerate(cells) if c in _CHAIN), None),
                    "case_ref": next((k for k, c in enumerate(cells) if c in _REF), None)}
        break
    rows = []
    for i, line in enumerate(lines):
        if i == header_at or not any(c.strip() for c in line):
            continue

        def cell(name: str) -> str | None:
            k = cols[name]
            value = line[k].strip() if k is not None and k < len(line) else ""
            return value or None

        rows.append({"row": i + 1, "address": cell("address") or "", "chain": cell("chain"),
                     "case_ref": cell("case_ref")})
    return rows


def check_size(rows: list[dict]) -> None:
    if not rows:
        raise BatchError("The upload holds no wallet. Give one address per line.")
    if len(rows) > MAX_ROWS:
        raise BatchError(f"The upload holds {len(rows)} rows; one batch takes at most "
                         f"{MAX_ROWS}. Split it into smaller files.")


def case_result(case: dict, risk: dict | None) -> dict:
    """What a finished case adds to its row of the result table. The exchange is the one
    the case names (nearest that clears the bar); its proximity and its confidence are
    two separate figures, as everywhere else."""
    top = next((c for c in case.get("candidates") or [] if c["vasp"] == case.get("top_vasp")
                and c.get("direction", "outbound") == "outbound"), None)
    budget = (case.get("provenance") or {}).get("budget") or {}
    return {"outcome": case.get("outcome"), "top_vasp": case.get("top_vasp"),
            "hops": top["hops"] if top else None,
            "proximity_rank": top["proximity_rank"] if top else None,
            "share_of_funds": top["share_of_funds"] if top else None,
            "confidence": case.get("confidence"),
            "risk_class": (risk or {}).get("risk_class"),
            "budget_ended": bool(budget.get("ended_by"))}


_NO_RESULT = {"outcome": None, "top_vasp": None, "hops": None, "proximity_rank": None,
              "share_of_funds": None, "confidence": None, "risk_class": None,
              "budget_ended": False}


def result_row(row: dict, head: dict | None, result: dict | None) -> dict:
    """One line of the result table (`S.BatchRow`): the row as uploaded, the state of its
    case (`head`: status, error), and the case's result once there is one."""
    out = {"row": row["row"], "address": row["address"], "chain": row.get("chain"),
           "case_ref": row.get("case_ref"), "accepted": bool(row.get("case_id")),
           "error": row.get("error"), "duplicate_of": row.get("duplicate_of"),
           "case_id": row.get("case_id"), "status": None, "case_url": None, **_NO_RESULT}
    if row.get("case_id"):
        out["case_url"] = f"/cases/{row['case_id']}"
        if head is not None:
            out["status"] = head["status"]
            if head["status"] == "failed":
                out["error"] = head.get("error") or "The trace failed."
            if result is not None:
                out.update(result)
    return out


def progress(rows: list[dict]) -> dict:
    """Counts over the result rows (`S.BatchProgress`). A duplicate row counts as
    accepted once, under the row it repeats."""
    cased = [r for r in rows if r["accepted"] and r.get("duplicate_of") is None]
    by_status = {s: sum(1 for r in cased if r["status"] == s)
                 for s in ("queued", "running", "done", "failed")}
    outcomes: dict[str, int] = {}
    for r in cased:
        if r["status"] == "done" and r["outcome"]:
            outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    return {"total": len(rows), "accepted": len(cased),
            "duplicates": sum(1 for r in rows if r.get("duplicate_of") is not None),
            "refused": sum(1 for r in rows if not r["accepted"]),
            **by_status, "by_outcome": dict(sorted(outcomes.items())),
            "finished": by_status["queued"] + by_status["running"] == 0}


def _cell(value) -> str:
    """A cell that a spreadsheet will show as text, never run as a formula."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def to_csv(rows: list[dict], base_url: str = "") -> str:
    """The result table as CSV, one line per uploaded row, in upload order."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(RESULT_COLUMNS)
    for r in rows:
        w.writerow([_cell(v) for v in (
            r["row"], r["address"], r["chain"], r["case_ref"],
            r["status"] or ("duplicate" if r.get("duplicate_of") else "refused"),
            r["outcome"], r["top_vasp"], r["hops"], r["proximity_rank"], r["share_of_funds"],
            r["confidence"], r["risk_class"], r["budget_ended"] if r["status"] == "done" else None,
            base_url + r["case_url"] if r["case_url"] else None, r["error"])])
    return out.getvalue()
