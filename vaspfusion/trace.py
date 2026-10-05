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

The budget is the officer's to raise: how many wallets are read per direction
(`max_nodes`, 40 unless raised), how deep (`max_hops`) and for how long
(`max_seconds`). The walk goes hop by hop, and within a hop the wallet holding the
largest share of the suspect's funds is read first, so whatever the budget, it is spent
where most of the money went. When the budget, not the evidence, is what stopped the
walk, the result says so (`TraceResult.budget_ended`) and the money left behind is
counted under the reason `budget`.

A time limit depends on the clock, so a trace it ended also records how many wallets
each direction had asked for by then (`stopped_after`). The same trace with that count
as `stop_after` stops at exactly the same wallet: this is how `verify` replays it.

A bridge is where money leaves a chain. When a trace is given `crossings`
(chains/bridges.py), each deposit into a labelled bridge is matched to its payout:
the bridge's index names the destination chain, the recipient and the payout
transaction, and the amount is read from that transaction on the destination chain
itself. The payout becomes a cross-chain edge from the bridge wallet to the recipient,
one hop further out, and the walk goes on from the recipient with the same rules.
What went in and did not come out is the bridge's fee and is held at the bridge as
such. A wallet on another chain has the id `chain:address` (chains/base.py), because
an EVM address is the same string on every EVM chain. A deposit that cannot be
matched, or that came out where no adapter reads, stays at the bridge as before, and
`TraceResult.crossings` says what was learnt about it.

Backward is the mirror image (the latest inflows before a payment explain it),
and a funder is only expanded when its whole inbound history came back, because
the adapters page oldest-first and cannot ask for "the transfers before t".
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from typing import Callable, Iterable, Protocol

from .chains.base import ProviderError, Transfer, TransferList, qualify, split_id
from .labels.lookup import Label
from .labels.normalize import VASP_CATEGORIES

ZERO = Decimal(0)
DEFAULT_WALLETS = 40             # the wallet budget every recorded case was traced with
MAX_WALLETS = 2000               # what the interface draws (`make ui-perf`)
_UNIT = Decimal("0.00000001")    # a satoshi: proportional parts on Bitcoin are whole satoshis
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
    max_seconds: float | None = None     # None = no time limit
    # (outbound, inbound): stop asking for new wallets after this many, None = no stop.
    # Set from a finished trace's `stopped_after` to replay a time-limited trace exactly:
    # when it is set the clock is not consulted, and `max_seconds` only records what the
    # officer asked for.
    stop_after: tuple[int | None, int | None] | None = None

    def __post_init__(self):
        if not 1 <= self.max_nodes <= MAX_WALLETS:
            raise ValueError(f"the wallet budget must be 1..{MAX_WALLETS}, not {self.max_nodes}")
        if self.max_seconds is not None and self.max_seconds <= 0:
            raise ValueError(f"the time budget must be positive, not {self.max_seconds}")
        if not 1 <= self.max_hops <= 5:
            raise ValueError(f"max_hops must be 1..5, not {self.max_hops}")
        if not 0 <= self.inbound_hops <= 5:
            raise ValueError(f"inbound_hops must be 0..5 (0 = do not look), not "
                             f"{self.inbound_hops}")


class LabelLookup(Protocol):
    def lookup_many(self, pairs: Iterable[tuple[str, str]]) -> dict[tuple[str, str], Label]: ...


@dataclass(frozen=True)
class Crossing:
    """One deposit into a bridge, and what became of it.

    `status`: "followed" (matched, and the payout was read on the destination chain),
    "not_traced" (matched: `hop` names the chain, recipient and payout transaction, but
    the trace could not go on there; `reason` says why), or "unresolved" (no match;
    `hop` is None)."""
    bridge_wallet: str           # id of the bridge wallet the deposit went into
    entity: str                  # the bridge, as its label names it
    deposit: Transfer
    traced_in: Decimal           # the part of the deposit that is the wallet's money
    status: str
    reason: str | None = None
    hop: object | None = None    # chains.bridges.BridgeHop
    payout: Transfer | None = None   # the transfer that paid the recipient (wallet ids)
    traced_out: Decimal = ZERO   # what of `traced_in` arrived; the rest is the bridge's fee


@dataclass(frozen=True)
class TraceEdge:
    transfer: Transfer
    side: str                    # "outbound" | "inbound"
    traced: Decimal              # the part of transfer.amount that is the wallet's money
    hop: int                     # hop of the wallet this edge reaches, away from the origin
    # set on a cross-chain edge: `transfer` is then the payout on the destination chain,
    # drawn from the bridge wallet (not from the contract that paid it) to the recipient
    crossing: Crossing | None = None


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
    # money that left this wallet into a transaction it cannot be followed through
    # (Bitcoin sinks): (side, reason, tx_hash, amount)
    sunk: list[tuple[str, str, str, Decimal]] = field(default_factory=list)
    chain: str | None = None     # the chain the wallet is on (None: the trace's own)


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
    # side -> "wallets" | "time": the budget, not the evidence, stopped that direction
    budget_ended: dict[str, str] = field(default_factory=dict)
    # side -> wallets it had asked for when the time ran out (see TraceConfig.stop_after)
    stopped_after: dict[str, int] = field(default_factory=dict)
    seconds: float | None = None     # how long the walk took, when a time budget was set
    crossings: list[Crossing] = field(default_factory=list)   # every bridge deposit met

    def expanded(self, side: str) -> int:
        return sum(1 for (s, _), n in self.nodes.items() if s == side and n.state == "expanded")

    def chain_of(self, wallet_id: str) -> str:
        return split_id(wallet_id, self.chain)[0]

    @property
    def chains(self) -> list[str]:
        """The chains the traced money was followed on, in the order it crossed."""
        seen = [self.chain]
        for c in sorted((c for c in self.crossings if c.status == "followed"),
                        key=lambda c: (c.payout.block_time, c.payout.tx_hash)):
            if c.payout.chain not in seen:
                seen.append(c.payout.chain)
        return seen

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
            if cur.crossing is not None:     # a payout is fed by its own deposit
                feeders = [e for e in feeders
                           if e.transfer == cur.crossing.deposit] or feeders
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


class _Reporter:
    """Tells whoever is watching a trace what it has read so far: the phase, how far out it
    is, how many wallets and transfers were read, and which labelled wallets the money has
    reached. It only counts: a trace with nobody watching is the same trace, and a listener
    that fails is not the trace's problem."""

    def __init__(self, on_progress: Callable[[dict], None] | None):
        self.tell = on_progress
        self.phase = "outbound"
        self.asset: str | None = None
        self.hop = 0
        self.wallets: set[str] = set()
        self.transfers = 0
        self.reached: list[dict] = []

    def emit(self) -> None:
        if self.tell is None:
            return
        try:
            self.tell({"phase": self.phase, "asset": self.asset, "hop": self.hop,
                       "wallets_read": len(self.wallets), "transfers_read": self.transfers,
                       "reached": [dict(r) for r in self.reached]})
        except Exception:  # noqa: BLE001 - a watcher that broke must not break the trace
            pass

    def read(self, address: str, transfers: int) -> None:
        """A wallet's listing came back with this many transfers."""
        self.wallets.add(address)
        self.transfers += transfers
        self.emit()

    def at_label(self, label: Label, hop: int) -> None:
        """The money reached a labelled wallet (each owner is named once)."""
        if any(r["entity"] == label.entity for r in self.reached):
            return
        self.reached.append({"entity": label.entity, "category": label.category, "hop": hop})
        self.emit()


class _Away:
    """Another chain's adapter, speaking wallet ids: asked about `chain:address`, it
    returns transfers whose two ends are ids too, so the walk keys them like any wallet."""

    def __init__(self, provider, chain: str, home: str):
        self.provider, self.chain, self.home = provider, chain, home
        self.traceable_assets = tuple(provider.traceable_assets)

    def transfers(self, wallet_id: str, direction: str, since=None, limit: int = 200,
                  asset: str | None = None) -> TransferList:
        raw = self.provider.transfers(split_id(wallet_id, self.home)[1], direction,
                                      since=since, limit=limit, asset=asset)
        return TransferList(
            [replace(t, from_addr=qualify(self.chain, t.from_addr, self.home),
                     to_addr=qualify(self.chain, t.to_addr, self.home)) for t in raw],
            complete=getattr(raw, "complete", True))


class _Walk:
    """One direction of the trace. `sign` = +1 forward in time (outbound), -1 backward."""

    def __init__(self, result: TraceResult, provider, labels: LabelLookup, cfg: TraceConfig,
                 side: str, report: _Reporter | None = None,
                 out_of_time: Callable[[], bool] | None = None, crossings=None):
        self.r, self.provider, self.labels, self.cfg, self.side = result, provider, labels, cfg, side
        self.home = result.chain
        # bridges are followed in the direction the money moved only
        self.cross = crossings if side == "outbound" else None
        self.away: dict[str, _Away] = {}
        self.asset_at: dict[str, str] = {}      # a wallet on another chain -> the asset followed
        self.payouts: dict[tuple[str, str, str], Transfer | None] = {}
        self.report = report or _Reporter(None)
        self.out_of_time = out_of_time or (lambda: False)
        self.stop_at = None if cfg.stop_after is None \
            else cfg.stop_after[0 if side == "outbound" else 1]
        self.tried: set[str] = set()     # wallets whose listing this walk asked for
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
        # `sink`: the stop reason of a transfer's far end when that is not an address but
        # a transaction the money cannot be followed through (chains/btc.py).
        self.infer = getattr(labels, "infer", None)
        self.inferred: set[str] = set()
        self.fee_of = getattr(provider, "fee_share", None) if side == "outbound" else None
        self.fee_used: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
        self.sink = getattr(provider, "sink_reason", None) or (lambda address: None)
        self.by_tx = getattr(provider, "fee_share", None) is not None   # a UTXO chain

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

    def sink_into(self, node: TraceNode, t: Transfer, amount: Decimal, reason: str) -> None:
        """`amount` of the wallet's money went into a transaction it cannot be followed
        through: it stops at the wallet, with the reason and the transaction."""
        self.hold(node, amount, reason)
        node.sunk.append((self.side, reason, t.tx_hash, amount))

    # ---------------------------------------------------------------- origin
    def start(self, asset: str, rows: list[Transfer], total: Decimal) -> None:
        self.asset, self.total = asset, total
        arrivals: dict[str, list[TraceEdge]] = defaultdict(list)
        for t in rows:
            reason = self.sink(self.far(t))
            if reason is not None:
                self.sink_into(self.r.nodes[("origin", self.r.address)], t, t.amount, reason)
                continue
            edge = TraceEdge(t, self.side, t.amount, 1)
            self.r.edges.append(edge)
            arrivals[self.far(t)].append(edge)
        for hop in range(1, self.max_hops + 1):
            if not arrivals:
                break
            arrivals = self.level(hop, arrivals)

    # ---------------------------------------------------------------- one hop
    def level(self, hop: int, arrivals: dict[str, list[TraceEdge]]) -> dict[str, list[TraceEdge]]:
        if self.side == "outbound":
            self.report.hop = max(self.report.hop, hop)
        new = [a for a in arrivals if (self.side, a) not in self.r.nodes and a != self.r.address]
        where = {a: split_id(a, self.home) for a in arrivals}       # id -> (chain, address)
        looked = self.labels.lookup_many([where[a][::-1] for a in sorted(new)])
        found = {a: looked.get(where[a][::-1]) for a in new}
        nxt: dict[str, list[TraceEdge]] = defaultdict(list)
        order = sorted(arrivals, key=lambda a: (-sum(e.traced for e in arrivals[a]), a))
        for addr in order:
            edges = arrivals[addr]
            got = sum((e.traced for e in edges), ZERO)
            if addr == self.r.address:           # the money came back to the wallet itself
                self.stopped["returned"] = self.stopped.get("returned", ZERO) + got
                continue
            node = self.r.nodes.get((self.side, addr))
            chain = where[addr][0]
            if node is None:
                node = TraceNode(addr, hop, self.side, found.get(addr), chain=chain)
                self.r.nodes[(self.side, addr)] = node
            node.received += got
            if chain != self.home:
                # one asset is followed per wallet: money that arrived in another stops here
                asset = self.asset_at.setdefault(addr, max(
                    edges, key=lambda e: (e.traced, e.transfer.asset)).transfer.asset)
                other = [e for e in edges if e.transfer.asset != asset]
                if other:
                    edges = [e for e in edges if e.transfer.asset == asset]
                    odd = sum((e.traced for e in other), ZERO)
                    self.hold(node, odd, "asset_changed")
                    got -= odd
            if node.label is None and self.infer is not None and addr not in self.inferred \
                    and chain == self.home \
                    and (not self.total or node.received / self.total >= self.cfg.min_share):
                self.inferred.add(addr)
                node.label = self.infer(addr, chain)
                if node.label is not None and node.held:
                    # it was holding money under another reason (too small to follow)
                    # before it had a name: that money is at a labelled wallet now
                    for was, amount in node.holds.items():
                        self.stopped[was] -= amount
                        if not self.stopped[was]:
                            del self.stopped[was]
                    held, node.held, node.holds, node.state = node.held, ZERO, {}, "labelled"
                    self.hold(node, held, "labelled")
            reason = self.why_not_expand(node, hop)
            if reason == "labelled" and self.side == "outbound":
                self.report.at_label(node.label, hop)
            if reason == "labelled" and self.cross is not None \
                    and node.label.category == "bridge":
                got = self.cross_over(node, edges, hop, nxt)    # what stays at the bridge
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
            left, fee = self.allocate(node, edges, rows, hop, nxt)
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
            self.r.budget_ended.setdefault(self.side, "wallets")
            return "budget"
        if self.stop_at is not None and len(self.tried) >= self.stop_at:
            self.r.budget_ended.setdefault(self.side, "time")
            self.r.stopped_after.setdefault(self.side, self.stop_at)
            return "budget"
        if self.out_of_time():
            self.r.budget_ended.setdefault(self.side, "time")
            self.r.stopped_after.setdefault(self.side, len(self.tried))
            return "budget"
        self.tried.add(node.address)
        return None

    def fetch(self, addr: str, edges: list[TraceEdge]) -> tuple[list[Transfer], bool]:
        """The wallet's transfers on the far side of the money: outflows since it
        arrived (outbound), or its whole inbound history (inbound)."""
        since = min(e.transfer.block_time for e in edges) if self.side == "outbound" else None
        cached = self.fetched.get(addr)
        if cached is None or (since is not None and cached[0] is not None and since < cached[0]):
            chain = self.r.chain_of(addr)
            provider = self.provider if chain == self.home else self.adapter(chain)
            raw = provider.transfers(addr, self.direction, since=since,
                                     limit=self.cfg.fetch_limit,
                                     asset=self.asset_at.get(addr, self.asset))
            self.report.read(addr, len(raw))
            cached = (since, self.usable(raw, addr), _complete(raw, self.cfg.fetch_limit))
            self.fetched[addr] = cached
        return cached[1], cached[2]

    def check_fetched(self, node: TraceNode, rows: list[Transfer], complete: bool) -> str | None:
        if len({self.far(t) for t in rows}) >= self.cfg.hub_degree:
            return "hub"
        if self.side == "inbound" and not complete:
            return "truncated"
        return None

    def allocate(self, node: TraceNode, edges: list[TraceEdge], rows: list[Transfer], hop: int,
                 nxt: dict[str, list[TraceEdge]]) -> tuple[Decimal, Decimal]:
        """Hand the money that arrived over `edges` to the wallet's next transfers in
        time order. Returns (what was left over, what went to network fees).

        On a UTXO chain the outputs of one transaction happen at once and its fee is
        paid with them, so they are served together: when the traced money does not
        cover all the wallet spent in that transaction, each output and the fee get
        their proportional part (not whichever address sorts first)."""
        addr = node.address
        # the fee share and the sinks are the home adapter's (Bitcoin); another chain's
        # wallets are plain accounts
        home = self.r.chain_of(addr) == self.home
        arrived = sorted(edges, key=lambda e: (self.when(e.transfer), e.transfer.tx_hash))
        rows = sorted(rows, key=lambda t: (self.when(t), t.tx_hash, self.far(t), t.amount))
        seen: Counter = Counter()
        pool, i, fees = ZERO, 0, ZERO
        for group in self._together(rows, home):
            first = group[0]
            while i < len(arrived) and self.when(arrived[i].transfer) <= self.when(first):
                pool += arrived[i].traced
                i += 1
            items = []
            for t in group:
                key = (t, seen[t])
                seen[t] += 1
                items.append((key, t, max(ZERO, t.amount - self.used[key])))
            paid = (addr, first.tx_hash)
            due = ZERO if self.fee_of is None or not home else \
                max(ZERO, self.fee_of(addr, first.tx_hash) - self.fee_used[paid])
            want = due + sum((a for _, _, a in items), ZERO)
            give = min(pool, want)
            if give <= 0:
                continue
            if give == want:
                takes, fee = [a for _, _, a in items], due
            elif len(items) == 1 and not due:
                takes, fee = [give], ZERO
            else:
                takes = [(give * a / want).quantize(_UNIT, rounding=ROUND_DOWN)
                         for _, _, a in items]
                fee = (give * due / want).quantize(_UNIT, rounding=ROUND_DOWN)
                # the few units rounding left over go to the largest part that has room
                j = max(range(len(items)), key=lambda k: (items[k][2], -k))
                takes[j] += min(give - sum(takes, ZERO) - fee, items[j][2] - takes[j])
            if fee > 0:
                self.fee_used[paid] += fee
                fees += fee
            pool -= fee + sum(takes, ZERO)
            for (key, t, _), take in zip(items, takes):
                if take <= 0:
                    continue
                self.used[key] += take
                reason = self.sink(self.far(t)) if home else None
                if reason is not None:
                    self.sink_into(node, t, take, reason)
                    continue
                edge = TraceEdge(t, self.side, take, hop + 1)
                self.r.edges.append(edge)
                nxt[self.far(t)].append(edge)
        return pool + sum((e.traced for e in arrived[i:]), ZERO), fees

    # ---------------------------------------------------------------- bridges
    def adapter(self, chain: str) -> _Away:
        if chain not in self.away:
            self.away[chain] = _Away(self.cross.provider(chain), chain, self.home)
        return self.away[chain]

    def cross_over(self, node: TraceNode, edges: list[TraceEdge], hop: int,
                   nxt: dict[str, list[TraceEdge]]) -> Decimal:
        """Money reached a bridge wallet over `edges`. Each deposit that can be matched
        to its payout goes on from the recipient on the destination chain; the bridge's
        fee is held here. Returns what stays at the bridge because it was not followed."""
        kept = ZERO
        for e in sorted(edges, key=lambda e: (self.when(e.transfer), e.transfer.tx_hash)):
            leg = self.leg(node, e, hop)
            self.r.crossings.append(leg)
            if leg.status != "followed":
                kept += e.traced
                continue
            self.hold(node, e.traced - leg.traced_out, "bridge_fee")
            edge = TraceEdge(replace(leg.payout, from_addr=node.address), self.side,
                             leg.traced_out, hop + 1, crossing=leg)
            self.r.edges.append(edge)
            nxt[leg.payout.to_addr].append(edge)
        return kept

    def leg(self, node: TraceNode, e: TraceEdge, hop: int) -> Crossing:
        t = e.transfer

        def stays(status: str, reason: str, found=None, payout=None) -> Crossing:
            return Crossing(node.address, node.label.entity, t, e.traced, status, reason,
                            found, payout)

        if self.total and e.traced / self.total < self.cfg.min_share:
            return stays("unresolved", "it is too small a part of the funds to follow")
        found = self.cross.resolve(node.label.entity, t)
        if not hasattr(found, "payout_tx"):
            return stays("unresolved", found.reason)
        if found.dest_chain is None:
            return stays("not_traced", f"{found.dest_name} is not a chain this tool reads",
                         found)
        if hop >= self.max_hops:
            return stays("not_traced", f"the trace's limit of {self.max_hops} hops was "
                                       "reached at the bridge", found)
        try:
            payout = self.payout(found)
        except ProviderError as err:
            return stays("not_traced", f"the recipient's transfers on {found.dest_name} "
                                       f"could not be read ({err})", found)
        if payout is None:
            return stays("not_traced", "the payout transaction shows no transfer of a "
                                       "followed asset to the recipient", found)
        same_money = t.asset == payout.asset or \
            (t.amount_usd is not None and payout.amount_usd is not None)
        if not same_money:
            return stays("not_traced", f"it was paid out in {payout.asset}, and a change of "
                                       f"asset from {t.asset} is not followed", found, payout)
        out = min(e.traced, (payout.amount * e.traced / t.amount)
                  .quantize(_UNIT, rounding=ROUND_DOWN))
        return Crossing(node.address, node.label.entity, t, e.traced, "followed", None, found,
                        payout, out)

    def payout(self, found) -> Transfer | None:
        """What the recipient received in the payout transaction, read from the
        destination chain: the bridge's own figure is a quote, this is what arrived."""
        key = (found.dest_chain, found.payout_tx, found.recipient)
        if key not in self.payouts:
            provider = self.adapter(found.dest_chain)
            wallet = qualify(found.dest_chain, found.recipient, self.home)
            self.payouts[key] = None
            for asset in provider.traceable_assets:
                rows = provider.transfers(wallet, "in", since=found.paid_at or found.deposited_at,
                                          limit=self.cfg.fetch_limit, asset=asset)
                paid = [t for t in rows if t.tx_hash == found.payout_tx and t.to_addr == wallet
                        and t.from_addr != wallet and t.amount > 0]
                if paid:
                    total = sum((t.amount for t in paid), ZERO)
                    self.payouts[key] = replace(
                        paid[0], amount=total,
                        amount_usd=None if paid[0].amount_usd is None else total)
                    break
        return self.payouts[key]

    def _together(self, rows: list[Transfer], home: bool = True) -> list[list[Transfer]]:
        """The rows that are served together: one transaction's rows on a UTXO chain,
        each row on its own everywhere else."""
        if not self.by_tx or not home:
            return [[t] for t in rows]
        groups: list[list[Transfer]] = []
        for t in rows:
            if groups and groups[-1][0].tx_hash == t.tx_hash:
                groups[-1].append(t)
            else:
                groups.append([t])
        return groups


def _pick_asset(provider, address: str, direction: str, cfg: TraceConfig, side: str
                ) -> tuple[str | None, list[Transfer], bool, dict[str, tuple[int, Decimal]]]:
    """Fetch each traceable asset on its own and choose the one to follow: the
    stablecoin with the largest total, else the native coin. With nothing to follow,
    the third value says whether that is because a listing could not be read at all (an
    adapter that returns nothing and says it is not the whole answer)."""
    per: dict[str, tuple[list[Transfer], bool]] = {}
    unread = False
    for asset in provider.traceable_assets:
        raw = provider.transfers(address, direction, since=cfg.since, limit=cfg.fetch_limit,
                                 asset=asset)
        mine = (lambda t: t.from_addr) if side == "outbound" else (lambda t: t.to_addr)
        rows = [t for t in raw if not _is_dust(t, cfg) and t.from_addr != t.to_addr
                and mine(t) == address]
        if rows:
            per[asset] = (rows, not _complete(raw, cfg.fetch_limit))
        elif not len(raw) and not getattr(raw, "complete", True):
            unread = True
    stable = {a: sum((t.amount_usd for t in rows), ZERO)
              for a, (rows, _) in per.items() if rows[0].amount_usd is not None}
    order = list(provider.traceable_assets)
    if stable:
        chosen = max(stable, key=lambda a: (stable[a], -order.index(a)))
    else:
        chosen = next((a for a in order if a in per), None)
    if chosen is None:
        return None, [], unread, {}
    rows, truncated = per[chosen]
    untraced = {a: (len(r), sum((t.amount for t in r), ZERO))
                for a, (r, _) in per.items() if a != chosen}
    return chosen, rows, truncated, untraced


def replay_config(cfg: TraceConfig, result: TraceResult) -> TraceConfig:
    """`cfg` with its clock switched off: the same walk as `result`, stopping where it
    stopped. A trace with no time limit is its own replay."""
    if cfg.max_seconds is None:
        return cfg
    cut = result.stopped_after
    return replace(cfg, stop_after=(cut.get("outbound"), cut.get("inbound")))


def trace(address: str, chain: str, provider, labels: LabelLookup,
          cfg: TraceConfig = TraceConfig(),
          on_progress: Callable[[dict], None] | None = None,
          clock: Callable[[], float] = time.monotonic, crossings=None) -> TraceResult:
    """`on_progress`, when given, is called with a snapshot each time the trace has read
    another wallet or reached a labelled one: `phase` (outbound, then inbound), `asset`,
    `hop` (how far out), `wallets_read`, `transfers_read`, `reached` (entity, category,
    hop). It changes nothing about the result.

    `crossings` (chains.bridges.Crossings), when given, lets the outbound walk follow
    money over the bridges it can match; without it a bridge is where the trail ends."""
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
    if hasattr(provider, "trace_from"):
        provider.trace_from(address)    # Bitcoin: whose multi-address spends may be split
    out_of_time = None
    timed = cfg.max_seconds is not None and cfg.stop_after is None
    if timed:
        start = clock()
        out_of_time = lambda: clock() - start >= cfg.max_seconds     # noqa: E731
    _walks(r, provider, labels, cfg, _Reporter(on_progress), out_of_time, crossings)
    if timed:
        r.seconds = clock() - start
    # what the label layer could not settle (Bitcoin clusters: an unread listing, two owners)
    r.notes += [n for n in getattr(labels, "notes", ()) if n not in r.notes]
    return r


def _walks(r: TraceResult, provider, labels: LabelLookup, cfg: TraceConfig,
           report: _Reporter, out_of_time: Callable[[], bool] | None = None,
           crossings=None) -> None:
    address = r.address
    # an adapter that lists newest-first cuts off the old end of a long history
    which = "most recent" if getattr(provider, "newest_first", False) and cfg.since is None \
        else "first"
    asset, rows, truncated, untraced = _pick_asset(provider, address, "out", cfg, "outbound")
    r.asset, r.untraced, r.truncated = asset, untraced, truncated
    r.total_out = sum((t.amount for t in rows), ZERO)
    report.asset = asset
    report.read(address, len(rows))
    if asset is None and truncated:
        since = f" back to {cfg.since.day} {cfg.since:%b %Y}" if cfg.since else ""
        r.notes.insert(0, f"The wallet's outgoing transfers could not be read{since}: it has "
                          "more transactions since then than one trace reads, so it was not "
                          "traced. A later start date will be within reach.")
    elif truncated:
        r.notes.append(f"Only the {which} {len(rows)} outgoing {asset} transfers were traced; "
                       "the wallet has more.")
    if asset is not None:
        _Walk(r, provider, labels, cfg, "outbound", report, out_of_time, crossings).start(
            asset, rows, r.total_out)

    if cfg.inbound_hops == 0:
        return
    in_asset, rows, truncated, _ = _pick_asset(provider, address, "in", cfg, "inbound")
    r.in_asset = in_asset
    r.total_in = sum((t.amount for t in rows), ZERO)
    report.phase = "inbound"
    report.read(address, len(rows))
    if truncated and in_asset is not None:
        r.notes.append(f"Only the {which} {len(rows)} incoming {in_asset} transfers were "
                       "looked at; the wallet has more.")
    if in_asset is not None:
        _Walk(r, provider, labels, cfg, "inbound", report, out_of_time).start(
            in_asset, rows, r.total_in)
