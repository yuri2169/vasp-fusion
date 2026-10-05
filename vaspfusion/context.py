"""The context of a case: the transfers its trace read and did not follow.

A case stores what the wallet's money did. What else the wallets on the trail did (their
other transfers, the dust they were sent, transfers in another asset) was read by the
trace and left out. This module gives it back on request, to be drawn greyed beside the
trail. It is context: it is never attributed, never on the Hop Rail and never counted
in a share of the funds, and asking for it changes nothing about the case.

Nothing extra is stored. The trace is run again from the responses the case was
computed from (as `verify` does), and the rows it reads and does not follow are the
context. A wallet the trace did not read has no recorded listing: its transfers are
fetched when the server is online, and reported as not recorded when it is not.
"""
from __future__ import annotations

from .cases import _label, replay_trace
from .chains.base import CacheMiss, InvalidAddress, ProviderError, Transfer, qualify, split_id
from .trace import TraceResult, _is_dust, context_rows, followed_rows

CONTEXT_LIMIT = 3000             # transfers returned at most; `transfers` is always the whole count
NOT_RECORDED = ("This wallet's other transfers were not recorded with the case: the trace "
                "did not read it. Online, they are read from the chain.")


def _why(tr: TraceResult, t: Transfer) -> str:
    if t in tr.dust or _is_dust(t, tr.config):
        return "dust"
    home = tr.chain_of(t.to_addr) == tr.chain
    if home and t.asset not in (tr.asset, tr.in_asset):
        return "other_asset"
    return "not_traced"


def _unread(tr: TraceResult, wallet: str, fetcher, provider_of) -> list[Transfer]:
    """The listing of a wallet the trace did not read, as wallet ids of this trace."""
    chain, address = split_id(wallet, tr.chain)
    provider = provider_of(chain)
    rows: dict[Transfer, None] = {}
    for direction in ("out", "in"):
        for t in provider.transfers(address, direction, since=tr.config.since,
                                    limit=tr.config.fetch_limit, asset=tr.asset):
            rows.setdefault(Transfer(**{
                **t.__dict__, "from_addr": qualify(chain, t.from_addr, tr.chain),
                "to_addr": qualify(chain, t.to_addr, tr.chain)}))
    drawn = followed_rows(tr) | {e.transfer for e in tr.edges}
    return [t for t in rows if t not in drawn]


def case_context(case: dict, replay_fetcher, labels, *, wallet: str | None = None,
                 fetcher=None, limit: int = CONTEXT_LIMIT, tr: TraceResult | None = None,
                 **provider_opts) -> dict:
    """`S.CaseContext` for a finished case: every transfer its trace read and did not
    follow, or those of one `wallet` (an id as in `graph.nodes`, or of a wallet already
    shown as context).

    `replay_fetcher` must be cache-only: the context is what the case's own trace read.
    `fetcher` (the server's, online or not) is only asked about a wallet the trace did
    not read. `tr` is a trace of this case already run again, to save running it twice.
    Raises KeyError for a wallet that is neither on the graph nor on any transfer read."""
    from .cases import trace_provider
    if tr is None:
        tr = replay_trace(case["provenance"]["input"], replay_fetcher, labels, **provider_opts)
    on_graph = {n["id"] for n in case["graph"]["nodes"]}
    rows = context_rows(tr)
    recorded, live, reason = True, False, None
    if wallet is not None:
        known = on_graph | {end for t in tr.seen for end in (t.from_addr, t.to_addr)}
        if wallet not in known:
            raise KeyError(wallet)
        if wallet in tr.read:
            rows = [t for t in rows if wallet in (t.from_addr, t.to_addr)]
        else:
            before = fetcher.stats["live"] if fetcher is not None else 0
            try:
                if fetcher is None:
                    raise CacheMiss("no fetcher")
                rows = _unread(tr, wallet, fetcher, lambda chain: trace_provider(
                    chain, fetcher, tr.config, **provider_opts))
                live = fetcher.stats["live"] > before
            except CacheMiss:
                rows, recorded, reason = [], False, NOT_RECORDED
            except (ProviderError, InvalidAddress) as e:
                rows, recorded = [], False
                reason = f"This wallet's transfers could not be read ({e})."
    total = len(rows)
    rows = sorted(rows[:limit], key=lambda t: (t.block_time, t.tx_hash, t.from_addr, t.to_addr))
    ends: dict[str, None] = {}
    for t in rows:
        ends.setdefault(t.from_addr)
        ends.setdefault(t.to_addr)
    where = {w: split_id(w, tr.chain) for w in ends}
    looked = labels.lookup_many(sorted({(a, c) for c, a in where.values()}))
    nodes = [{"id": w, "address": where[w][1], "chain": where[w][0], "on_graph": w in on_graph,
              "label": _label(looked.get((where[w][1], where[w][0])))} for w in ends]
    edges = [{"id": f"x{i}", "tx_hash": t.tx_hash, "source": t.from_addr, "target": t.to_addr,
              "asset": t.asset, "amount": float(t.amount),
              "amount_usd": None if t.amount_usd is None else float(t.amount_usd),
              "block_time": t.block_time, "chain": tr.chain_of(t.to_addr), "why": _why(tr, t)}
             for i, t in enumerate(rows, 1)]
    if wallet is None:
        text = (f"{total:,} other transfer{'' if total == 1 else 's'} of the "
                f"{len(tr.read):,} wallet{'' if len(tr.read) == 1 else 's'} this trace read.")
    elif recorded:
        text = f"{total:,} other transfer{'' if total == 1 else 's'} of this wallet."
    else:
        text = reason
    if recorded:
        text += " They are context, not the suspect wallet's money."
    return {"case_id": case["id"], "wallet": wallet, "recorded": recorded, "live": live,
            "reason": reason, "transfers": total, "truncated": total > len(rows),
            "nodes": nodes, "edges": edges, "text": text}
