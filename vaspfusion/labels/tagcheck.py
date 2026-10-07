"""Is an explorer's deposit tag borne out on chain?

Upstream files 5,000 Ethereum addresses that Etherscan tags "Binance Dep: 0x..." under
another exchange's name (`bilaxy`), so the owner cannot be read from the row alone. This
check reads each address's own transfers and records two things: was the address ever
used, and where does it send its money on. The loader (load.py) names an address after
the tag only when the check saw it used and saw nothing that contradicts the tag.

The result is a tracked CSV, one row per address, so `make labels` needs no network.
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from ..chains import ProviderError
from .normalize import VASP_CATEGORIES

COLUMNS = ["address", "chain", "tag", "seen", "n_rows", "complete", "first_seen", "n_out",
           "top_recipient", "top_recipient_entity", "verdict", "error"]
# confirmed: used, and the wallet it pays most is a labelled wallet of the tagged exchange
# used: used, and the wallet it pays most carries no exchange label (or it never paid out)
# contradicted: used, and the wallet it pays most is another exchange's labelled wallet
# unused: no transfer found
# unread: the listing could not be read; nothing is concluded
VERDICTS = ("confirmed", "used", "contradicted", "unused", "unread")
LOADED = ("confirmed", "used")          # the verdicts the loader accepts


def _exchange_wallet(label) -> bool:
    """A labelled wallet of an exchange itself: from a source, and not a deposit address
    (the rule discovery starts from, discover/rules.py::is_seed)."""
    return (label is not None and label.category in VASP_CATEGORIES
            and label.tier != "derived" and label.kind != "deposit")


def tag_owner(label: str) -> str | None:
    """'Binance Dep: 0xabc...' -> 'Binance'. None when the label is not a deposit tag."""
    head, sep, _ = (label or "").partition(" Dep:")
    return head.strip() or None if sep else None


def check_address(provider, labels, address: str, chain: str, owner: str,
                  limit: int = 50) -> dict:
    row = {"address": address, "chain": chain, "tag": f"{owner} Dep", "seen": "", "n_rows": "",
           "complete": "", "first_seen": "", "n_out": "", "top_recipient": "",
           "top_recipient_entity": "", "verdict": "unread", "error": ""}
    try:
        rows = provider.transfers(address, "both", limit=limit)
    except ProviderError as e:
        row["error"] = str(e)[:200]
        return row
    row.update(seen=int(bool(rows)), n_rows=len(rows), complete=int(rows.complete))
    if not rows:
        row["verdict"] = "unused"
        return row
    row["first_seen"] = min(t.block_time for t in rows).strftime("%Y-%m-%dT%H:%M:%SZ")
    paid = Counter(t.to_addr for t in rows if t.from_addr == address and t.to_addr != address)
    row["n_out"] = sum(paid.values())
    row["verdict"] = "used"
    if paid:
        top = min(paid, key=lambda a: (-paid[a], a))
        lab = labels.lookup(top, chain)
        row["top_recipient"] = top
        if _exchange_wallet(lab):
            row["top_recipient_entity"] = lab.entity
            row["verdict"] = "confirmed" if lab.entity == owner else "contradicted"
    return row


def run(provider, labels, targets: list[tuple[str, str, str]], limit: int = 50,
        progress=None) -> list[dict]:
    """`targets`: (address, chain, owner). Rows come back sorted by chain and address."""
    out = []
    for i, (address, chain, owner) in enumerate(sorted(targets, key=lambda t: (t[1], t[0]))):
        out.append(check_address(provider, labels, address, chain, owner, limit))
        if progress and (i + 1) % 250 == 0:
            progress(i + 1, len(targets), summary(out))
    return out


def summary(rows: list[dict]) -> dict:
    counts = Counter(r["verdict"] for r in rows)
    return {"checked": len(rows), **{v: counts.get(v, 0) for v in VERDICTS}}


def write_csv(rows: list[dict], path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def read_checks(folder: Path | str | None) -> dict[tuple[str, str], dict]:
    """Every check file in the folder, keyed by (address, chain). No folder: no checks."""
    out: dict[tuple[str, str], dict] = {}
    if folder is None or not Path(folder).is_dir():
        return out
    for path in sorted(Path(folder).glob("*.csv")):
        with path.open(newline="") as f:
            for r in csv.DictReader(f):
                out[(r["address"], r["chain"])] = r
    return out
