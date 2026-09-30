"""Risk spread from known-bad wallets along the payment graph.

Kept apart from the detector on purpose: sitting near a watchlisted wallet is a
reason to look, not evidence the model found anything, so it is never blended
into the model's score. Spread stops at very high-degree actors (exchanges,
payment processors): past one of those every customer would inherit the taint.
"""
from __future__ import annotations

import csv
import io
import re

import polars as pl

_ADDR = re.compile(r"^[A-Za-z0-9]{14,100}$")
_SCHEMA = {"entity": pl.Utf8, "seed": pl.Utf8, "direction": pl.Utf8, "parent": pl.Utf8}


def parse_watchlist(text: str, default_label: str) -> tuple[list[tuple[str, str]], int]:
    """'address[,label]' per line, optional header. Returns (rows, n_rejected)."""
    rows, bad = [], 0
    for line in csv.reader(io.StringIO(text)):
        if not line or not line[0].strip() or line[0].strip().lower() == "address":
            continue
        addr = line[0].strip()
        label = (line[1].strip() if len(line) > 1 and line[1].strip() else default_label)[:80]
        if _ADDR.match(addr):
            rows.append((addr, label))
        else:
            bad += 1
    return rows, bad


def propagate(edges: pl.DataFrame, seeds: dict[str, str], max_hops: int = 3,
              decay: float = 0.5, hub_degree: int = 200) -> pl.DataFrame:
    """Hop-limited spread from seed actors over src->dst payment edges.

    One row per actor reached, seeds included at hop 0: entity, seed, direction
    ('seed' | 'downstream' = money came from the seed | 'upstream' = money went to
    the seed; a path never switches direction), parent (previous actor on the
    path), hops, risk = decay ** hops, is_hub (reached but not spread through).
    Nearest seed wins; ties break on seed, then direction, then parent, so the
    result does not depend on row order.
    """
    e = edges.select(["src", "dst"]).unique()
    deg = (pl.concat([e.select(pl.col("src").alias("entity")),
                      e.select(pl.col("dst").alias("entity"))]).group_by("entity").len())
    hubs = deg.filter(pl.col("len") > hub_degree).get_column("entity").to_list()
    fwd = e.rename({"src": "entity", "dst": "next"})
    back = e.rename({"dst": "entity", "src": "next"})
    s = sorted(seeds)
    frontier = pl.DataFrame({"entity": s, "seed": s, "direction": ["seed"] * len(s),
                             "parent": [None] * len(s)}, schema=_SCHEMA)
    reached = frontier.with_columns(pl.lit(0, dtype=pl.Int32).alias("hops"))
    for hop in range(1, max_hops + 1):
        grow = frontier.filter((pl.col("direction") == "seed") | ~pl.col("entity").is_in(hubs))
        steps = [grow.filter(pl.col("direction").is_in(["seed", name]))
                     .join(adj, on="entity")
                     .select(pl.col("next").alias("entity"), "seed",
                             pl.lit(name).alias("direction"), pl.col("entity").alias("parent"))
                 for name, adj in (("downstream", fwd), ("upstream", back))]
        nxt = (pl.concat(steps)
               .join(reached.select("entity"), on="entity", how="anti")
               .sort(["entity", "seed", "direction", "parent"])
               .unique("entity", keep="first", maintain_order=True))
        if nxt.height == 0:
            break
        reached = pl.concat([reached, nxt.with_columns(pl.lit(hop, dtype=pl.Int32).alias("hops"))])
        frontier = nxt
    return (reached.with_columns(pl.lit(decay).pow(pl.col("hops")).alias("risk"),
                                 pl.col("entity").is_in(hubs).alias("is_hub"))
            .sort(["hops", "entity"]))


def paths(reached: pl.DataFrame) -> dict[str, list[str]]:
    """entity -> [entity, ..., seed], following parent pointers."""
    parent = dict(zip(reached.get_column("entity").to_list(),
                      reached.get_column("parent").to_list()))
    out = {}
    for ent in parent:
        p = [ent]
        while parent.get(p[-1]) is not None:
            p.append(parent[p[-1]])
        out[ent] = p
    return out


def nearest_with_queued(reached: pl.DataFrame, queued: set[str], limit: int) -> pl.DataFrame:
    """The `limit` nearest actors, plus every queued lead however far down the
    list it sits, so a truncated response never undercounts the queue."""
    keep = reached.head(limit)
    extra = reached.slice(limit).filter(pl.col("entity").is_in(list(queued)))
    return pl.concat([keep, extra])
