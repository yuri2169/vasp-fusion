"""Typology flags: patterns in how a traced wallet's money moved.

A flag is something for the officer to look at, never a verdict. None of them
decides the outcome (the label flags are the one exception the attribution rules
read: money at a sanctioned or mixer label sets SANCTIONED_OR_MIXER_REACHED). Each
flag names the wallet, gives the figures it was raised on and lists the
transaction hashes, so it can be checked by hand on a block explorer.

Every flag reads the traced money only (`TraceEdge.traced`), not a wallet's whole
history: "fan-out" means this wallet's money was spread, not that the wallet is busy.

* sanctioned_contact / mixer_contact / bridge_hop: traced money reached (or the
  wallet was funded by) an address with that label.
* peel_chain: consecutive wallets that each send most of the money on to one next
  wallet and peel the rest off to others.
* rapid_forwarding: an unlabelled wallet passed on nearly everything that reached
  it, each part within minutes of arriving.
* fan_out: one wallet paid the money out to many wallets in a short time.
* fan_in: the wallet was funded by many senders, or split money merged again.
* round_amounts: most of the wallet's stablecoin payments are whole hundreds.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from ..explain import fmt
from ..trace import ZERO, TraceEdge, TraceResult

ALERT_CATEGORIES = {"sanctioned": "sanctioned_contact", "mixer": "mixer_contact"}
_SEVERITY = {"high": 0, "warn": 1, "info": 2}
_CODES = ["sanctioned_contact", "mixer_contact", "bridge_hop", "peel_chain", "rapid_forwarding",
          "fan_out", "fan_in", "round_amounts"]


@dataclass(frozen=True)
class TypologyConfig:
    fan_out_recipients: int = 5        # distinct wallets paid ...
    fan_out_hours: float = 24.0        # ... inside this window
    fan_in_senders: int = 5            # distinct funders of the wallet
    merge_senders: int = 3             # traced wallets that pay one wallet
    rapid_share: float = 0.90          # passed on at least this much ...
    rapid_seconds: int = 600           # ... each part within this long of arriving
    peel_main_share: float = 0.70      # sent on to one wallet; the rest is peeled
    peel_wallets: int = 2              # consecutive peeling wallets
    round_unit: int = 100              # stablecoin units
    round_transfers: int = 3
    round_share: float = 0.5


def _flag(code: str, severity: str, wallet: str, text: str, figures: dict,
          edges: list[TraceEdge]) -> dict:
    return {"code": code, "severity": severity, "wallet": wallet, "text": text,
            "figures": {k: float(v) for k, v in figures.items()},
            "tx_hashes": sorted({e.transfer.tx_hash for e in edges})}


def _when(e: TraceEdge) -> float:
    return e.transfer.block_time.timestamp()


class _View:
    """The outbound side of a trace, by wallet."""

    def __init__(self, tr: TraceResult):
        self.tr = tr
        self.asset = tr.asset
        self.sent: dict[str, list[TraceEdge]] = defaultdict(list)
        self.got: dict[str, list[TraceEdge]] = defaultdict(list)
        for e in tr.edges:
            if e.side == "outbound":
                self.sent[e.transfer.from_addr].append(e)
                self.got[e.transfer.to_addr].append(e)
        for edges in (*self.sent.values(), *self.got.values()):
            edges.sort(key=lambda e: (_when(e), e.transfer.tx_hash, e.transfer.to_addr))

    def received(self, wallet: str) -> Decimal:
        if wallet == self.tr.address:
            return self.tr.total_out
        return sum((e.traced for e in self.got[wallet]), ZERO)

    def unlabelled(self, wallet: str) -> bool:
        node = self.tr.nodes.get(("outbound", wallet))
        return wallet != self.tr.address and node is not None and node.label is None


# ------------------------------------------------------------------ labels
def _label_flags(tr: TraceResult) -> list[dict]:
    flags: list[dict] = []
    lab = tr.origin_label
    if lab is not None and lab.category in ALERT_CATEGORIES:
        flags.append({"code": ALERT_CATEGORIES[lab.category], "severity": "high",
                      "wallet": tr.address, "figures": {}, "tx_hashes": [],
                      "text": f"The wallet itself is labelled {lab.entity} ({lab.category})"})
    for (side, addr), node in tr.nodes.items():
        if side == "origin" or node.label is None or node.received <= 0:
            continue
        cat = node.label.category
        if cat not in ALERT_CATEGORIES and cat != "bridge":
            continue
        total = tr.total_out if side == "outbound" else tr.total_in
        asset = tr.asset if side == "outbound" else tr.in_asset
        share = float(node.received / total)
        what = {"sanctioned": "a sanctioned address", "mixer": "a mixer",
                "bridge": "a bridge"}[cat]
        if side == "outbound":
            text = (f"{fmt.pct(share)} of the funds ({fmt.amount(node.received, asset)}) reached "
                    f"{what}, {fmt.short(addr)} ({node.label.entity}), {fmt.hops(node.hop)} away")
        else:
            text = (f"{fmt.pct(share)} of what the wallet received "
                    f"({fmt.amount(node.received, asset)}) was funded by {what}, "
                    f"{fmt.short(addr)} ({node.label.entity})")
        flags.append(_flag(ALERT_CATEGORIES.get(cat, "bridge_hop"),
                           "high" if cat in ALERT_CATEGORIES else "warn", addr, text,
                           {"share": round(share, 4), "amount": node.received, "hops": node.hop},
                           tr.edges_into(side, addr)))
    return flags


# ------------------------------------------------------------------ behaviour
def _fan_out(v: _View, cfg: TypologyConfig) -> list[dict]:
    flags = []
    span = cfg.fan_out_hours * 3600
    for wallet, edges in v.sent.items():
        best: list[TraceEdge] = []
        start = 0
        for end in range(len(edges)):
            while _when(edges[end]) - _when(edges[start]) > span:
                start += 1
            window = edges[start:end + 1]
            if len({e.transfer.to_addr for e in window}) > len({e.transfer.to_addr for e in best}):
                best = window
        recipients = len({e.transfer.to_addr for e in best})
        if recipients < cfg.fan_out_recipients:
            continue
        amount = sum((e.traced for e in best), ZERO)
        took = _when(best[-1]) - _when(best[0])
        flags.append(_flag("fan_out", "info", wallet,
                           f"{fmt.short(wallet)} paid {fmt.amount(amount, v.asset)} to "
                           f"{recipients} wallets within {fmt.duration(took)}",
                           {"recipients": recipients, "amount": amount,
                            "hours": round(took / 3600, 2)}, best))
    return flags


def _fan_in(v: _View, cfg: TypologyConfig) -> list[dict]:
    tr, flags = v.tr, []
    funders = [e for e in tr.edges if e.side == "inbound" and e.hop == 1]
    senders = {e.transfer.from_addr for e in funders}
    if len(senders) >= cfg.fan_in_senders:
        amount = sum((e.traced for e in funders), ZERO)
        flags.append(_flag("fan_in", "info", tr.address,
                           f"{fmt.short(tr.address)} was funded by {len(senders)} wallets "
                           f"({fmt.amount(amount, tr.in_asset)} in all)",
                           {"senders": len(senders), "amount": amount}, funders))
    for wallet, edges in v.got.items():
        senders = {e.transfer.from_addr for e in edges}
        if wallet == tr.address or len(senders) < cfg.merge_senders:
            continue
        amount = sum((e.traced for e in edges), ZERO)
        flags.append(_flag("fan_in", "info", wallet,
                           f"{fmt.amount(amount, v.asset)} of the wallet's money came together "
                           f"again at {fmt.short(wallet)}, from {len(senders)} wallets it had "
                           "been split across",
                           {"senders": len(senders), "amount": amount}, edges))
    return flags


def _rapid(v: _View, cfg: TypologyConfig) -> list[dict]:
    flags = []
    for wallet, sent in v.sent.items():
        got = v.got.get(wallet)
        if not got or not v.unlabelled(wallet):
            continue
        received = v.received(wallet)
        passed = sum((e.traced for e in sent), ZERO)
        if received <= 0 or float(passed / received) < cfg.rapid_share:
            continue
        slowest = 0.0
        for e in sent:                       # timed from the latest arrival before it left
            before = [_when(a) for a in got if _when(a) <= _when(e)]
            if not before:
                slowest = float("inf")
                break
            slowest = max(slowest, _when(e) - before[-1])
        if slowest > cfg.rapid_seconds:
            continue
        flags.append(_flag("rapid_forwarding", "warn", wallet,
                           f"{fmt.short(wallet)} passed on {fmt.pct(passed / received)} of the "
                           f"{fmt.amount(received, v.asset)} that reached it "
                           + ("in the same block" if slowest == 0 else
                              f"within {fmt.duration(slowest)} of its arrival"),
                           {"share": round(float(passed / received), 4), "amount": received,
                            "seconds": slowest}, got + sent))
    return flags


def _peels(v: _View, wallet: str, cfg: TypologyConfig) -> tuple[str, Decimal] | None:
    """(the wallet most of the money went on to, what was peeled off), if `wallet` peels."""
    received = v.received(wallet)
    to: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for e in v.sent.get(wallet, ()):
        to[e.transfer.to_addr] += e.traced
    if len(to) < 2 or received <= 0:
        return None
    main = min(to, key=lambda a: (-to[a], a))
    if float(to[main] / received) < cfg.peel_main_share:
        return None
    return main, sum(to.values(), ZERO) - to[main]


def _peel_chain(v: _View, cfg: TypologyConfig) -> list[dict]:
    peel = {w: p for w in v.sent if (p := _peels(v, w, cfg)) is not None}
    continued = {main for main, _ in peel.values()}
    flags = []
    for start in peel:
        if start in continued and start != v.tr.address:
            continue                                   # the middle of a chain, not its start
        chain, peeled, seen = [], ZERO, set()
        w = start
        while w in peel and w not in seen:
            seen.add(w)
            chain.append(w)
            peeled += peel[w][1]
            w = peel[w][0]
        if len(chain) < cfg.peel_wallets:
            continue
        amount = v.received(start)
        flags.append(_flag("peel_chain", "warn", start,
                           f"Peel chain of {len(chain)} wallets: "
                           f"{' → '.join(fmt.short(a) for a in chain)} each sent most of the "
                           f"money on to one wallet and peeled the rest off to others "
                           f"({fmt.amount(peeled, v.asset)} of {fmt.amount(amount, v.asset)} "
                           "peeled off in all)",
                           {"wallets": len(chain), "amount": amount, "peeled": peeled},
                           [e for a in chain for e in v.sent[a]]))
    return flags


def _round_amounts(v: _View, cfg: TypologyConfig) -> list[dict]:
    first = [e for e in v.sent.get(v.tr.address, ()) if e.transfer.amount_usd is not None]
    round_ = [e for e in first if e.transfer.amount >= cfg.round_unit
              and e.transfer.amount % cfg.round_unit == 0]
    if len(round_) < cfg.round_transfers or len(round_) < cfg.round_share * len(first):
        return []
    amount = sum((e.transfer.amount for e in round_), ZERO)
    return [_flag("round_amounts", "info", v.tr.address,
                  f"{len(round_)} of the wallet's {len(first)} {v.asset} payments are whole "
                  f"multiples of {cfg.round_unit} ({fmt.amount(amount, v.asset)} in all)",
                  {"round_transfers": len(round_), "transfers": len(first), "amount": amount},
                  round_)]


def typology_flags(tr: TraceResult, cfg: TypologyConfig = TypologyConfig()) -> list[dict]:
    flags = _label_flags(tr)
    if tr.asset is not None:
        v = _View(tr)
        flags += _peel_chain(v, cfg) + _rapid(v, cfg) + _fan_out(v, cfg) + _fan_in(v, cfg) \
            + _round_amounts(v, cfg)
    elif tr.in_asset is not None:
        flags += _fan_in(_View(tr), cfg)
    flags.sort(key=lambda f: (_SEVERITY[f["severity"]], _CODES.index(f["code"]),
                              -f["figures"].get("share", 1.0),
                              -f["figures"].get("amount", 0.0), f["wallet"]))
    return flags
