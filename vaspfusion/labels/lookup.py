"""Read-only lookups against data/labels.duckdb (built by `make labels`)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import duckdb
import pyarrow as pa

from .load import LABEL_COLUMNS
from .normalize import EVM_CHAINS, VASP_CATEGORIES, normalize_address, normalize_chain

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "labels.duckdb"


@dataclass(frozen=True)
class Label:
    address: str
    chain: str
    entity: str
    category: str
    kind: str
    tier: str
    source: str
    source_url: str | None
    label: str | None
    confidence: float | None = None     # derived labels only (model-scored or rule-set)
    evidence: str | None = None         # derived labels only: what the rules saw
    confidence_low: float | None = None   # model-scored labels only: the calibrated range
    confidence_high: float | None = None
    reasons: str | None = None          # model-scored labels only: JSON list of top reasons

    @property
    def is_vasp(self) -> bool:
        return self.category in VASP_CATEGORIES

    def as_dict(self) -> dict:
        d = asdict(self)
        d["reasons"] = json.loads(self.reasons) if self.reasons else None
        return d


def _chains_for(chain: str) -> list[str]:
    """The chain itself, then the chain-agnostic EVM rows for any EVM chain.
    An EOA is the same key on every EVM chain, so a Dune "EVM" CoinDCX wallet is
    CoinDCX on BSC too; a chain-specific row always wins over the generic one."""
    return [chain, "evm"] if chain in EVM_CHAINS and chain != "evm" else [chain]


class LabelStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB):
        path = Path(db_path)
        if not path.exists():
            raise FileNotFoundError(f"{path} not found - run `make labels`")
        self.con = duckdb.connect(str(path), read_only=True)
        # a DB built before B4 has no confidence / evidence columns, one built before B6
        # no range / reasons: read them as NULL
        have = {r[0] for r in self.con.execute("DESCRIBE labels").fetchall()}
        self._select = [c if c in have else f"NULL AS {c}" for c in LABEL_COLUMNS]
        self._cols = ", ".join(self._select)

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "LabelStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def lookup(self, address: str, chain: str) -> Label | None:
        c = normalize_chain(chain)
        for ch in _chains_for(c):
            row = self.con.execute(f"SELECT {self._cols} FROM labels "
                                   "WHERE address = ? AND chain = ?",
                                   [normalize_address(address, ch), ch]).fetchone()
            if row:
                return Label(*row)
        return None

    def lookup_many(self, pairs: Iterable[tuple[str, str]]) -> dict[tuple[str, str], Label]:
        pairs = list(dict.fromkeys(pairs))
        if not pairs:
            return {}
        # One query for the lot: expand each input to its candidate (address, chain)
        # keys with a priority, join, and keep the best per input.
        keys = []
        for i, (addr, chain) in enumerate(pairs):
            c = normalize_chain(chain)
            for prio, ch in enumerate(_chains_for(c)):
                keys.append((i, prio, normalize_address(addr, ch), ch))
        i, prio, address, chain = zip(*keys)
        self.con.register("_q", pa.table({"i": i, "prio": prio, "address": address,
                                          "chain": chain}))
        rows = self.con.execute(
            f"SELECT q.i, {', '.join(c if ' AS ' in c else 'l.' + c for c in self._select)} "
            "FROM _q q "
            "JOIN labels l USING (address, chain) "
            "QUALIFY row_number() OVER (PARTITION BY q.i ORDER BY q.prio) = 1").fetchall()
        self.con.unregister("_q")
        return {pairs[r[0]]: Label(*r[1:]) for r in rows}

    def search(self, q: str = "", chain: str | None = None, category: str | None = None,
               tier: str | None = None, limit: int = 50, offset: int = 0
               ) -> tuple[int, list[Label]]:
        where, params = [], []
        q = q.strip()
        if q:
            where.append("(address ILIKE ? OR entity ILIKE ? OR label ILIKE ?)")
            params += [f"{q}%", f"%{q}%", f"%{q}%"]
        for col, val in (("chain", chain), ("category", category), ("tier", tier)):
            if val:
                where.append(f"{col} = ?")
                params.append(val)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        total = self.con.execute(f"SELECT count(*) FROM labels {clause}", params).fetchone()[0]
        rows = self.con.execute(
            f"SELECT {self._cols} FROM labels {clause} ORDER BY entity, chain, address "
            "LIMIT ? OFFSET ?", [*params, int(limit), int(offset)]).fetchall()
        return total, [Label(*r) for r in rows]

    def seeds(self, chain: str) -> list[Label]:
        """The chain's labelled exchange wallets that B4's discovery starts from: VASP
        categories, not derived and not themselves deposit addresses."""
        rows = self.con.execute(
            f"SELECT {self._cols} FROM labels WHERE chain = ? AND category IN "
            f"({', '.join('?' * len(VASP_CATEGORIES))}) AND tier <> 'derived' "
            "AND kind <> 'deposit' ORDER BY entity, address",
            [normalize_chain(chain), *sorted(VASP_CATEGORIES)]).fetchall()
        return [Label(*r) for r in rows]

    def non_deposit(self, chain: str) -> list[Label]:
        """A chain's labels from the sources that are not deposit addresses: exchange
        wallets, sanctioned addresses, services. The deposit model's known negatives."""
        rows = self.con.execute(
            f"SELECT {self._cols} FROM labels WHERE chain = ? AND tier <> 'derived' "
            "AND kind <> 'deposit' ORDER BY address", [normalize_chain(chain)]).fetchall()
        return [Label(*r) for r in rows]

    def by_tier(self, chain: str, tier: str) -> list[Label]:
        """Every label of one tier on a chain, by address (the hold-out test samples
        its ground truth from the explorer-tagged ones)."""
        rows = self.con.execute(
            f"SELECT {self._cols} FROM labels WHERE chain = ? AND tier = ? ORDER BY address",
            [normalize_chain(chain), tier]).fetchall()
        return [Label(*r) for r in rows]

    def stats(self) -> dict:
        from .load import label_stats
        return label_stats(self.con)


def lookup(address: str, chain: str, db: str | Path = DEFAULT_DB) -> Label | None:
    with LabelStore(db) as s:
        return s.lookup(address, chain)


def lookup_batch(pairs: Iterable[tuple[str, str]], db: str | Path = DEFAULT_DB
                 ) -> dict[tuple[str, str], Label]:
    with LabelStore(db) as s:
        return s.lookup_many(pairs)
