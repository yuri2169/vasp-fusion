"""Follow a wallet's money: forward to where it went, backward to who funded it.

The walk is breadth-first over the chain adapters. One asset is followed: the
stablecoin the wallet sent most of, or the native coin if it sent no stablecoin.
Tokens the adapter does not recognise (`SYMBOL@contract`) are never followed,
which is also what keeps address-poisoning spoofs out of the graph.

Allocation rule ("first out after arrival"): traced money that reached a wallet
at time t is assigned to that wallet's next outgoing transfers of the same asset
at or after t, in time order, each taking min(what is left, the transfer amount).
What is left has not moved on and is held at that wallet. A transfer's amount is
used at most once, so a wallet reached by two routes cannot double-count. Every
unit the wallet sent therefore ends in exactly one place, and `stopped` says why.

A wallet is not expanded when it is labelled (an exchange, bridge, mixer, any
named party), is a hub (many distinct counterparties: commingled funds), sits at
the hop limit, holds too little of the funds, or the budget is spent.

Backward is the mirror image (the latest inflows before a payment explain it),
and a funder is only expanded when its whole inbound history came back, because
the adapters page oldest-first and cannot ask for "the transfers before t".
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Protocol

from .chains.base import ProviderError, Transfer
from .labels.lookup import Label
from .labels.normalize import VASP_CATEGORIES

ZERO = Decimal(0)
# Native-coin transfers below this are dust (address poisoning, gas refunds).
DUST_NATIVE = {"TRX": Decimal(1), "BTC": Decimal("0.00001")}
# A wallet with one of these labels is a service: its transfers are not "its money".
SERVICE_CATEGORIES = VASP_CATEGORIES | {"bridge", "mixer", "defi"}


@dataclass(frozen=True)
class TraceConfig:
    max_hops: int = 3            # outbound depth
    inbound_hops: int = 1        # who funded the wallet
    fetch_limit: int = 100       # transfers fetched per wallet
    hub_degree: int = 30         # distinct counterparties in one fetch -> hub
    dust_usd: Decimal = Decimal(1)
    dust_native: Decimal = Decimal("0.001")
    min_share: Decimal = Decimal("0.01")
    max_nodes: int = 40          # wallets expanded per direction
    since: datetime | None = None

    def __post_init__(self):
        if not 1 <= self.max_hops <= 5:
            raise ValueError(f"max_hops must be 1..5, not {self.max_hops}")
        if not 0 <= self.inbound_hops <= 5:
            raise ValueError(f"inbound_hops must be 0..5 (0 = do not look), not "
                             f"{self.inbound_hops}")


class LabelLookup(Protocol):
    def lookup_many(self, pairs: Iterable[tuple[str, str]]) -> dict[tuple[str, str], Label]: ...


@dataclass(frozen=True)
class TraceEdge:
    transfer: Transfer
    side: str                    # "outbound" | "inbound"
    traced: Decimal              # the part of transfer.amount that is the wallet's money
    hop: int                     # hop of the wallet this edge reaches, away from the origin


@dataclass
class TraceNode:
    address: str
    hop: int
    side: str                    # "origin" | "outbound" | "inbound"
    label: Label | None = None
    state: str = "pending"
    received: Decimal = ZERO     # traced money that reached it (outbound) / left it (inbound)
    held: Decimal = ZERO         # the part that stopped here
    holds: dict[str, Decimal] = field(default_factory=dict)   # ... and why: reason -> amount
    note: str | None = None


@dataclass
class TraceResult:
    address: str
    chain: str
    asset: str | None = None
    total_out: Decimal = ZERO
    in_asset: str | None = None
    total_in: Decimal = ZERO
    nodes: dict[tuple[str, str], TraceNode] = field(default_factory=dict)
    edges: list[TraceEdge] = field(default_factory=list)
    stopped: dict[str, Decimal] = field(default_factory=dict)      # outbound: reason -> amount
    stopped_in: dict[str, Decimal] = field(default_factory=dict)   # inbound
    truncated: bool = False
    untraced: dict[str, tuple[int, Decimal]] = field(default_factory=dict)
    origin_label: Label | None = None
    notes: list[str] = field(default_factory=list)
    config: TraceConfig = field(default_factory=TraceConfig)

    def edges_into(self, side: str, address: str) -> list[TraceEdge]:
        """Traced transfers that reach `address`, walking away from the origin."""
        return [e for e in self.edges if e.side == side and _far(e) == address]

    def path_of(self, edge: TraceEdge) -> list[TraceEdge]:
        """The route the money on `edge` took between the origin and it, in the order
        the money moved. Each step back takes the largest transfer that had already
        delivered money to the wallet when the next one left it (mirrored for inbound),
        so a path is always a real route and never runs backwards in time."""
        sign = 1 if edge.side == "outbound" else -1
        path = [edge]
        while path[-1].hop > 1:
            cur = path[-1]
            when = sign * cur.transfer.block_time.timestamp()
            feeders = [e for e in self.edges_into(cur.side, _near(cur))
                       if e.hop == cur.hop - 1
                       and sign * e.transfer.block_time.timestamp() <= when]
            path.append(max(feeders, key=lambda e: (
                e.traced, sign * e.transfer.block_time.timestamp(), e.transfer.tx_hash)))
        return path[::-1] if edge.side == "outbound" else path

    def path_to(self, side: str, address: str) -> list[TraceEdge]:
        """The nearest route between the origin and `address` (the one carrying the most,
        if several are equally short), in the order the money moved."""
        into = self.edges_into(side, address)
        if not into:
            return []
        return self.path_of(min(into, key=lambda e: (e.hop, -e.traced,
                                                     e.transfer.block_time, e.transfer.tx_hash)))

    def to_igraph(self):
        """Directed graph of every traced transfer; vertex `name` is the address."""
        import igraph as ig
        names: dict[str, TraceNode] = {}
        for side in ("origin", "outbound", "inbound"):   # an address seen both ways: outbound wins
            for (s, addr), node in self.nodes.items():
                if s == side:
                    names.setdefault(addr, node)
        order = list(names)
        index = {a: i for i, a in enumerate(order)}
        g = ig.Graph(directed=True)
        g.add_vertices(len(order))
        g.vs["name"] = order
        g.vs["hop"] = [names[a].hop for a in order]
        g.vs["side"] = [names[a].side for a in order]
        g.vs["state"] = [names[a].state for a in order]
        g.vs["entity"] = [names[a].label.entity if names[a].label else None for a in order]
        g.vs["category"] = [names[a].label.category if names[a].label else None for a in order]
        g.add_edges([(index[e.transfer.from_addr], index[e.transfer.to_addr])
                     for e in self.edges])
        g.es["tx_hash"] = [e.transfer.tx_hash for e in self.edges]
        g.es["traced"] = [float(e.traced) for e in self.edges]
        g.es["amount"] = [float(e.transfer.amount) for e in self.edges]
        g.es["time"] = [e.transfer.block_time.timestamp() for e in self.edges]
        g.es["side"] = [e.side for e in self.edges]
        return g


def _far(e: TraceEdge) -> str:
    return e.transfer.to_addr if e.side == "outbound" else e.transfer.from_addr


def _near(e: TraceEdge) -> str:
    return e.transfer.from_addr if e.side == "outbound" else e.transfer.to_addr


def _complete(raw, limit: int) -> bool:
    """Did the adapter return the wallet's whole listing? Adapters say so themselves
    (`TransferList.complete`); a plain list is complete if it came back under the limit."""
    return len(raw) < limit and getattr(raw, "complete", True)


def _is_dust(t: Transfer, cfg: TraceConfig) -> bool:
    if t.amount <= 0:
        return True
    if t.amount_usd is not None:
        return t.amount_usd < cfg.dust_usd
    return t.amount < DUST_NATIVE.get(t.asset, cfg.dust_native)


class _Walk:
    """One direction of the trace. `sign` = +1 forward in time (outbound), -1 backward."""

    def __init__(self, result: TraceResult, provider, labels: LabelLookup, cfg: TraceConfig,
                 side: str):
        self.r, self.provider, self.labels, self.cfg, self.side = result, provider, labels, cfg, side
        self.sign = 1 if side == "outbound" else -1
        self.direction = "out" if side == "outbound" else "in"
        self.max_hops = cfg.max_hops if side == "outbound" else cfg.inbound_hops
        self.stopped = result.stopped if side == "outbound" else result.stopped_in
        self.used: dict[tuple[Transfer, int], Decimal] = defaultdict(lambda: ZERO)
        self.fetched: dict[str, tuple[datetime | None, list[Transfer], bool]] = {}
        self.expanded: set[str] = set()
        # Bitcoin (B5). `infer`: a label derived from the wallet's cluster, asked for only
        # when the wallet has none of its own and holds enough of the funds to matter.
        # `fee_of`: the wallet's share of a transaction's miner fee, which leaves with the
        # money it spends and would otherwise be counted as "has not moved on".
        self.infer = getattr(labels, "infer", None)
        self.inferred: set[str] = set()
        self.fee_of = getattr(provider, "fee_share", None) if side == "outbound" else None
        self.fee_used: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)

    # the wallet at the far end of a transfer, seen from the origin
    def far(self, t: Transfer) -> str:
        return t.to_addr if self.side == "outbound" else t.from_addr

    def near(self, t: Transfer) -> str:
        return t.from_addr if self.side == "outbound" else t.to_addr

    def when(self, t: Transfer) -> float:
        return self.sign * t.block_time.timestamp()

    def usable(self, rows: list[Transfer], address: str) -> list[Transfer]:
        return [t for t in rows if not _is_dust(t, self.cfg) and self.far(t) != self.near(t)
                and self.near(t) == address]

    def hold(self, node: TraceNode, amount: Decimal, reason: str) -> None:
        if amount > 0:
            node.held += amount
            node.holds[reason] = node.holds.get(reason, ZERO) + amount
            self.stopped[reason] = self.stopped.get(reason, ZERO) + amount

    # ---------------------------------------------------------------- origin
    def start(self, asset: str, rows: list[Transfer], total: Decimal) -> None:
        self.asset, self.total = asset, total
        arrivals: dict[str, list[TraceEdge]] = defaultdict(list)
        for t in rows:
            edge = TraceEdge(t, self.side, t.amount, 1)
            self.r.edges.append(edge)
            arrivals[self.far(t)].append(edge)
        for hop in range(1, self.max_hops + 1):
            if not arrivals:
                break
            arrivals = self.level(hop, arrivals)

    # ---------------------------------------------------------------- one hop
    def level(self, hop: int, arrivals: dict[str, list[TraceEdge]]) -> dict[str, list[TraceEdge]]:
        chain = self.r.chain
        new = [a for a in arrivals if (self.side, a) not in self.r.nodes and a != self.r.address]
        found = self.labels.lookup_many([(a, chain) for a in sorted(new)])
        nxt: dict[str, list[TraceEdge]] = defaultdict(list)
        order = sorted(arrivals, key=lambda a: (-sum(e.traced for e in arrivals[a]), a))
        for addr in order:
            edges = arrivals[addr]
            got = sum((e.traced for e in edges), ZERO)
            if addr == self.r.address:           # the money came back to the wallet itself
                self.stopped["returned"] = self.stopped.get("returned", ZERO) + got
                continue
            node = self.r.nodes.get((self.side, addr))
            if node is None:
                node = TraceNode(addr, hop, self.side, found.get((addr, chain)))
                self.r.nodes[(self.side, addr)] = node
            node.received += got
            if node.label is None and self.infer is not None and addr not in self.inferred \
                    and (not self.total or node.received / self.total >= self.cfg.min_share):
                self.inferred.add(addr)
                node.label = self.infer(addr, chain)
            reason = self.why_not_expand(node, hop)
            if reason is None:
                try:
                    rows, complete = self.fetch(addr, edges)
                except ProviderError as e:
                    reason, node.note = "error", str(e)
                else:
                    reason = self.check_fetched(node, rows, complete)
            if reason is not None:
                if node.state in ("pending", "expanded") and addr not in self.expanded:
                    node.state = reason
                self.hold(node, got, reason)
                continue
            node.state = "expanded"
            self.expanded.add(addr)
            left, fee = self.allocate(addr, edges, rows, hop, nxt)
            self.hold(node, fee, "fee")
            # behind a cut-off fetch the rest may well have moved on; we did not see it
            self.hold(node, left, "unspent" if complete else "truncated")
        return nxt

    def why_not_expand(self, node: TraceNode, hop: int) -> str | None:
        if node.label is not None:
            return "labelled"
        if node.state in ("hub", "error", "truncated"):
            return node.state
        if hop >= self.max_hops:
            return "depth_limit"
        if node.address in self.expanded:
            return None
        if self.total and node.received / self.total < self.cfg.min_share:
            return "small"
        if len(self.expanded) >= self.cfg.max_nodes:
            return "budget"
        return None

    def fetch(self, addr: str, edges: list[TraceEdge]) -> tuple[list[Transfer], bool]:
        """The wallet's transfers on the far side of the money: outflows since it
        arrived (outbound), or its whole inbound history (inbound)."""
        since = min(e.transfer.block_time for e in edges) if self.side == "outbound" else None
        cached = self.fetched.get(addr)
        if cached is None or (since is not None and cached[0] is not None and since < cached[0]):
            raw = self.provider.transfers(addr, self.direction, since=since,
                                          limit=self.cfg.fetch_limit, asset=self.asset)
            cached = (since, self.usable(raw, addr), _complete(raw, self.cfg.fetch_limit))
            self.fetched[addr] = cached
        return cached[1], cached[2]

    def check_fetched(self, node: TraceNode, rows: list[Transfer], complete: bool) -> str | None:
        if len({self.far(t) for t in rows}) >= self.cfg.hub_degree:
            return "hub"
        if self.side == "inbound" and not complete:
            return "truncated"
        return None

    def allocate(self, addr: str, edges: list[TraceEdge], rows: list[Transfer], hop: int,
                 nxt: dict[str, list[TraceEdge]]) -> tuple[Decimal, Decimal]:
        """Hand the money that arrived over `edges` to the wallet's next transfers in
        time order. Returns (what was left over, what went to network fees). A fee is
        only known on UTXO chains: there a transaction's fee is paid first, once, out of
        the money that is spent in it."""
        arrived = sorted(edges, key=lambda e: (self.when(e.transfer), e.transfer.tx_hash))
        rows = sorted(rows, key=lambda t: (self.when(t), t.tx_hash, self.far(t), t.amount))
        seen: Counter = Counter()
        pool, i, fees = ZERO, 0, ZERO
        for t in rows:
            key = (t, seen[t])
            seen[t] += 1
            while i < len(arrived) and self.when(arrived[i].transfer) <= self.when(t):
                pool += arrived[i].traced
                i += 1
            if self.fee_of is not None:
                paid = (addr, t.tx_hash)
                fee = min(pool, self.fee_of(addr, t.tx_hash) - self.fee_used[paid])
                if fee > 0:
                    self.fee_used[paid] += fee
                    pool -= fee
                    fees += fee
            take = min(pool, t.amount - self.used[key])
            if take <= 0:
                continue
            self.used[key] += take
            pool -= take
            edge = TraceEdge(t, self.side, take, hop + 1)
            self.r.edges.append(edge)
            nxt[self.far(t)].append(edge)
        return pool + sum((e.traced for e in arrived[i:]), ZERO), fees


def _pick_asset(provider, address: str, direction: str, cfg: TraceConfig, side: str
                ) -> tuple[str | None, list[Transfer], bool, dict[str, tuple[int, Decimal]]]:
    """Fetch each traceable asset on its own and choose the one to follow: the
    stablecoin with the largest total, else the native coin."""
    per: dict[str, tuple[list[Transfer], bool]] = {}
    for asset in provider.traceable_assets:
        raw = provider.transfers(address, direction, since=cfg.since, limit=cfg.fetch_limit,
                                 asset=asset)
        mine = (lambda t: t.from_addr) if side == "outbound" else (lambda t: t.to_addr)
        rows = [t for t in raw if not _is_dust(t, cfg) and t.from_addr != t.to_addr
                and mine(t) == address]
        if rows:
            per[asset] = (rows, not _complete(raw, cfg.fetch_limit))
    stable = {a: sum((t.amount_usd for t in rows), ZERO)
              for a, (rows, _) in per.items() if rows[0].amount_usd is not None}
    order = list(provider.traceable_assets)
    if stable:
        chosen = max(stable, key=lambda a: (stable[a], -order.index(a)))
    else:
        chosen = next((a for a in order if a in per), None)
    if chosen is None:
        return None, [], False, {}
    rows, truncated = per[chosen]
    untraced = {a: (len(r), sum((t.amount for t in r), ZERO))
                for a, (r, _) in per.items() if a != chosen}
    return chosen, rows, truncated, untraced


def trace(address: str, chain: str, provider, labels: LabelLookup,
          cfg: TraceConfig = TraceConfig()) -> TraceResult:
    r = TraceResult(address=address, chain=chain, config=cfg)
    r.origin_label = labels.lookup_many([(address, chain)]).get((address, chain))
    infer = getattr(labels, "infer", None)
    if r.origin_label is None and infer is not None:
        r.origin_label = infer(address, chain)
    r.nodes[("origin", address)] = TraceNode(address, 0, "origin", r.origin_label, state="origin")
    if r.origin_label is not None and r.origin_label.category in SERVICE_CATEGORIES:
        r.notes.append(f"The address is itself labelled {r.origin_label.entity} "
                       f"({r.origin_label.category}); a service wallet is not traced.")
        return r
    _walks(r, provider, labels, cfg)
    # what the label layer could not settle (Bitcoin clusters: an unread listing, two owners)
    r.notes += [n for n in getattr(labels, "notes", ()) if n not in r.notes]
    return r


def _walks(r: TraceResult, provider, labels: LabelLookup, cfg: TraceConfig) -> None:
    address = r.address
    # an adapter that lists newest-first cuts off the old end of a long history
    which = "most recent" if getattr(provider, "newest_first", False) and cfg.since is None \
        else "first"
    asset, rows, truncated, untraced = _pick_asset(provider, address, "out", cfg, "outbound")
    r.asset, r.untraced, r.truncated = asset, untraced, truncated
    r.total_out = sum((t.amount for t in rows), ZERO)
    if truncated:
        r.notes.append(f"Only the {which} {len(rows)} outgoing {asset} transfers were traced; "
                       "the wallet has more.")
    if asset is not None:
        _Walk(r, provider, labels, cfg, "outbound").start(asset, rows, r.total_out)

    if cfg.inbound_hops == 0:
        return
    in_asset, rows, truncated, _ = _pick_asset(provider, address, "in", cfg, "inbound")
    r.in_asset = in_asset
    r.total_in = sum((t.amount for t in rows), ZERO)
    if truncated:
        r.notes.append(f"Only the {which} {len(rows)} incoming {in_asset} transfers were "
                       "looked at; the wallet has more.")
    if in_asset is not None:
        _Walk(r, provider, labels, cfg, "inbound").start(in_asset, rows, r.total_in)
