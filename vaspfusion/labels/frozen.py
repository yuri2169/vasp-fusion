"""Addresses Tether has frozen: USDT's blacklist, replayed from the contracts' own events.

`cli frozen` (chains/usdt_freeze.py does the reading) replays every `AddedBlackList` and
`RemovedBlackList` event of USDT on Tron and Ethereum in order, up to a fixed cut-off,
which leaves the addresses frozen at that moment and the date each was (last) frozen.
A seeded sample is then put to the contract's own `isBlackListed` call. The result is
a dated snapshot, data/usdt_frozen.csv with data/usdt_frozen.json beside it (tracked,
so the offline demo has it).

What a match establishes: the issuer put the address on the token's blacklist, on that
date, and had not taken it off at the cut-off. It does not give the reason, and it says
nothing about anyone who dealt with the address. A frozen address is a mark, never the
name of its owner: it is not a label, and a trace walks through it.
"""
from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = ROOT / "data" / "usdt_frozen.csv"
COLUMNS = ["address", "chain", "asset", "issuer", "frozen_at", "tx_hash", "contract"]
CATEGORY = "frozen"
ISSUER = "Tether"
ASSET = "USDT"
CONTRACTS = {"tron": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
             "ethereum": "0xdac17f958d2ee523a2206206994597c13d831ec7"}
SOURCE = ("USDT token contracts on Tron and Ethereum: every AddedBlackList and "
          "RemovedBlackList event, replayed in order")
MEANING = ("The issuer put this address on the token's blacklist on that date, and had not "
           "taken it off when the list was read. It does not say why, and it says nothing "
           "about anyone who dealt with the address.")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _key(address: str, chain: str) -> tuple[str, str]:
    return (address.lower() if chain == "ethereum" else address, chain)


def _order(e: dict) -> tuple:
    return (e["time_ms"], e["block"], e["tx"], e["index"])


def replay(events: list[dict]) -> dict[tuple[str, str], dict]:
    """(address, chain) -> {frozen_at_ms, tx_hash, block} for every address frozen after
    the events, taken in chain order. A second freeze while frozen keeps the first date;
    a freeze after a release dates from the new one."""
    now: dict[tuple[str, str], dict] = {}
    for e in sorted(events, key=_order):
        k = _key(e["address"], e["chain"])
        if e["event"] == "AddedBlackList":
            now.setdefault(k, {"frozen_at_ms": e["time_ms"], "tx_hash": e["tx"],
                               "block": e["block"]})
        elif e["event"] == "RemovedBlackList":
            now.pop(k, None)
        else:
            raise ValueError(f"not a blacklist event: {e['event']}")
    return now


def released(events: list[dict]) -> list[tuple[str, str]]:
    """Addresses that were frozen and then taken off, and not frozen again."""
    now = replay(events)
    off = {_key(e["address"], e["chain"]) for e in events if e["event"] == "RemovedBlackList"}
    return sorted(off - set(now))


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_snapshot(now: dict[tuple[str, str], dict], path: Path | str = DEFAULT_CSV,
                   meta: dict | None = None) -> dict:
    """Write the CSV and its metadata; return the metadata."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(((c, a), v) for (a, c), v in now.items())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(COLUMNS)
        for (chain, address), v in rows:
            w.writerow([address, chain, ASSET, ISSUER, iso(v["frozen_at_ms"]), v["tx_hash"],
                        CONTRACTS[chain]])
    counts: dict[str, int] = {}
    for (chain, _), _v in rows:
        counts[chain] = counts.get(chain, 0) + 1
    meta = {**(meta or {}), "counts": dict(sorted(counts.items())), "total": len(rows)}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
    return meta


def check_sample(frozen: dict[tuple[str, str], dict], gone: list[tuple[str, str]], n: int,
                 seed: int) -> list[tuple[str, str, bool]]:
    """(address, chain, expected answer): `n` frozen and `n` released addresses, drawn
    with `seed`, to put to the contract's own call."""
    rng = random.Random(seed)
    yes = sorted(frozen)
    pick = rng.sample(yes, min(n, len(yes))) + rng.sample(sorted(gone), min(n, len(gone)))
    return [(a, c, (a, c) in frozen) for a, c in pick]


def mark_text(hit: dict) -> str:
    """'Frozen by Tether on 3 Aug 2024'."""
    d = datetime.strptime(hit["frozen_at"][:10], "%Y-%m-%d")
    return f"Frozen by {hit['issuer']} on {d.day} {_MONTHS[d.month - 1]} {d.year}"


class FreezeList:
    def __init__(self, rows: dict[tuple[str, str], dict], meta: dict):
        self.rows, self.meta = rows, meta

    @classmethod
    def load(cls, path: Path | str | None = None) -> "FreezeList":
        return _load(str(path or DEFAULT_CSV))

    def lookup(self, address: str, chain: str) -> dict | None:
        if not address or chain not in CONTRACTS:
            return None
        return self.rows.get(_key(address, chain))

    def many(self, pairs) -> dict[tuple[str, str], dict]:
        out = {}
        for address, chain in pairs:
            hit = self.lookup(address, chain)
            if hit is not None:
                out[(address, chain)] = hit
        return out

    def search(self, chain: str | None = None, q: str | None = None,
               limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        rows = [r for r in self.rows.values()
                if (chain is None or r["chain"] == chain)
                and (not q or q.lower() in r["address"].lower())]
        rows.sort(key=lambda r: (r["chain"], r["address"]))
        return rows[offset:offset + limit], len(rows)

    def stats(self) -> dict:
        by: dict[str, int] = {}
        for _, chain in self.rows:
            by[chain] = by.get(chain, 0) + 1
        return {"total": len(self.rows), "by_chain": dict(sorted(by.items())),
                "fetched_at": self.meta.get("fetched_at"), "cutoff": self.meta.get("cutoff")}


@lru_cache(maxsize=4)
def _load(path: str) -> FreezeList:
    p = Path(path)
    if not p.exists():
        return FreezeList({}, {})
    rows = {}
    with p.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows[_key(r["address"], r["chain"])] = dict(r)
    meta_path = p.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return FreezeList(rows, meta)
