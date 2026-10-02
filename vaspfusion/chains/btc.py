"""Bitcoin: an address's history from an Esplora API, as address-to-address transfers
that say only what the chain says.

A Bitcoin transaction has many inputs and many outputs and does not record which input
paid which output. So an address's coins are followed through a transaction only where
that question has one answer, and are otherwise parked in a SINK the trace stops at.

OUTBOUND (`out_transfers`). An address that put in `v` of the transaction's `V` input
value has a share `v / V` of every output (rounded down to a satoshi; `fee_share` is
what is left of `v`, so shares, change and fee add up to `v` exactly).

* Followed, because it is certain: the address is the transaction's only input address
  (every output is its payment), or everything goes to one destination (many addresses
  swept into one: each sent its share there). An output back to the address itself is
  its change and stays put; an output to ANOTHER input address is a transfer to it.
* `pooled:<txid>`: several input addresses AND several destinations. Which destination
  this address's coins paid is not on the chain. An exchange's sweep that also pays out
  withdrawals has exactly this form, and splitting it pro rata would send a depositor's
  coins on to somebody else's withdrawal.
* The one exception is the wallet being traced (`own=True`): the addresses it is spent
  with are its own (common-input ownership), so every output is that wallet's payment
  and its share of each is followed. Not when five or more addresses fund the
  transaction or it looks like a small join (`join_like`): then it is pooled too.
* `coinjoin:<txid>`: the transaction has the shape of a CoinJoin (`coinjoin_ids`).
* `no-address:<txid>`: outputs with no address form (pay-to-pubkey, bare multisig).

INBOUND (`in_transfers`), one row per transaction: what it paid the address, from the
input address that put in the most (ties: the smaller string). Under common-input
ownership every input is that same sender; vaspfusion/cluster.py reads them all. A
payment out of a CoinJoin comes from `coinjoin:<txid>`, newly mined coins from
`block-reward:<txid>`, inputs with no address form from `no-address:<txid>`.

BACKENDS. blockstream.info and mempool.space serve the same Esplora API.
`/address/{a}/txs` returns the newest confirmed transactions plus any unconfirmed ones;
`/txs/chain/{last_txid}` pages further back. The first page held 50 confirmed
transactions when measured (1 Oct 2026; the docs say 25), so a page with fewer than 25
is taken as the last one rather than trusting a size. Unconfirmed transactions are
skipped (no block time; they would break a deterministic replay). The backend is part
of every request and so of every cache key: a replay needs the backend it was recorded
from (`VASPFUSION_BTC_API`, default blockstream.info).

The API is newest-first only. Without `since` the most recent `limit` transfers are
returned. With `since`, pages are followed back to it and the earliest `limit` are
returned; if `max_pages` runs out first NOTHING is returned (`complete=False`): the
transfers nearest to `since` are the ones that were not read.
"""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .addresses import validate
from .base import (ChainProvider, Direction, InvalidAddress, ProviderError, Transfer,
                   TransferList, sort_transfers, utc_from_s)
from .cache import Fetcher

ESPLORA = {"blockstream.info": "https://blockstream.info/api",
           "mempool.space": "https://mempool.space/api"}
DEFAULT_API = "blockstream.info"
LAST_PAGE_BELOW = 25
MIN_MIX = 10_000    # satoshis: equal outputs smaller than this are dust, not a mix
MIN_EQUAL = 5       # equal-value outputs a CoinJoin has at least (Whirlpool has exactly 5)
MIN_SHARE = 0.25    # ... and their part of all outputs (real Wasabi 1.x rounds: 26% to 51%)
POOL_INPUTS = 5     # this many funding addresses: not one person's ordinary payment
# Sinks: where coins go that cannot be followed. `<prefix>:<txid>` -> the trace's stop reason.
SINKS = {"coinjoin": "coinjoin", "pooled": "pooled", "no-address": "no_address",
         "block-reward": "mined"}


def sink_reason(address: str) -> str | None:
    """The stop reason if `address` is a sink id, None if it is an address."""
    prefix, colon, _ = address.partition(":")
    return SINKS.get(prefix) if colon else None


def _sink(prefix: str, tx: "UtxoTx") -> str:
    return f"{prefix}:{tx.txid}"


@dataclass(frozen=True)
class UtxoTx:
    txid: str
    time: datetime                                  # block time, UTC
    inputs: tuple[tuple[str | None, int], ...]      # (address, satoshis) per input
    outputs: tuple[tuple[str | None, int], ...]     # (address, satoshis) per output
    coinbase: bool = False                          # pays out a block reward

    @property
    def fee(self) -> int:
        paid_in = sum(v for _, v in self.inputs)
        return max(0, paid_in - sum(v for _, v in self.outputs)) if paid_in else 0

    @property
    def input_addresses(self) -> list[str]:
        """Distinct input addresses, in input order."""
        return list(dict.fromkeys(a for a, _ in self.inputs if a))

    def put_in(self, address: str) -> int:
        return sum(v for a, v in self.inputs if a == address)

    def paid_to(self, address: str) -> int:
        return sum(v for a, v in self.outputs if a == address)

    def equal_block(self) -> tuple[int, int]:
        """(value, count) of the largest block of equal-value outputs; the larger value
        on a tie, as graph/coinjoin.py reads it."""
        counts = Counter(v for a, v in self.outputs if a)
        if not counts:
            return 0, 0
        return max(counts.items(), key=lambda kv: (kv[1], kv[0]))

    @classmethod
    def from_esplora(cls, tx: dict) -> "UtxoTx":
        vin = tx.get("vin", [])
        ins = tuple(((v.get("prevout") or {}).get("scriptpubkey_address"),
                     int((v.get("prevout") or {}).get("value") or 0)) for v in vin)
        outs = tuple((o.get("scriptpubkey_address"), int(o.get("value") or 0))
                     for o in tx.get("vout", []))
        return cls(tx["txid"], utc_from_s(tx["status"]["block_time"]), ins, outs,
                   coinbase=any(v.get("is_coinbase") for v in vin))


def _btc(satoshis: int) -> Decimal:
    return Decimal(satoshis).scaleb(-8)


def _transfer(tx: UtxoTx, frm: str, to: str, satoshis: int, payer: str) -> Transfer:
    return Transfer("bitcoin", tx.txid, tx.time, frm, to, "BTC", _btc(satoshis), None, payer)


def _shares(tx: UtxoTx, address: str) -> tuple[dict[str | None, int], int]:
    """(the address's share of what each output address was paid, its share of the fee),
    in satoshis. Shares are rounded down; the fee share is what is left of what the
    address put in, so the two always add up to it exactly."""
    mine, total = tx.put_in(address), sum(v for _, v in tx.inputs)
    if not mine or not total:
        return {}, 0
    paid: dict[str | None, int] = {}
    for to, value in tx.outputs:
        paid[to] = paid.get(to, 0) + value
    shares = {to: value * mine // total for to, value in paid.items()}
    return shares, mine - sum(shares.values())


def fee_share(tx: UtxoTx, address: str) -> Decimal:
    """The address's part of the miner fee: pro rata by what it put in (plus the
    satoshis that rounding its output shares down left over)."""
    return _btc(_shares(tx, address)[1])


def join_like(tx: UtxoTx) -> bool:
    """Two or more equal-value outputs and at least as many funding addresses: the shape
    of a joint transaction of several owners (a small CoinJoin, a marketplace sale).
    Such a transaction's inputs are not taken as one owner, and nobody's coins are
    followed through it."""
    _, equal = tx.equal_block()
    return equal >= 2 and len(tx.input_addresses) >= equal


def out_transfers(tx: UtxoTx, address: str, coinjoin: bool = False,
                  own: bool = False) -> list[Transfer]:
    """What `address` sent in `tx` (see the module docstring). `own`: the address is the
    wallet being traced."""
    shares, _ = _shares(tx, address)
    # what left the address: every output but its own change; zero outputs carry nothing
    left = {to: v for to, v in shares.items() if to != address and v}
    if not left:
        return []
    funders = tx.input_addresses

    def sink(prefix: str) -> list[Transfer]:
        return [_transfer(tx, address, _sink(prefix, tx), sum(left.values()), address)]

    if coinjoin:
        return sink("coinjoin")
    certain = len(funders) == 1 or len(left) == 1
    if not certain and not (own and len(funders) < POOL_INPUTS and not join_like(tx)):
        return sink("pooled")
    rows = [_transfer(tx, address, to, v, address) for to, v in left.items() if to]
    if left.get(None):
        rows.append(_transfer(tx, address, _sink("no-address", tx), left[None], address))
    return rows


def in_transfers(tx: UtxoTx, address: str, coinjoin: bool = False) -> list[Transfer]:
    """What `tx` paid `address`, unless the address is one of its own inputs (change)."""
    got = tx.paid_to(address)
    if not got or address in tx.input_addresses:
        return []
    by_address: dict[str, int] = {}
    for a, v in tx.inputs:
        if a:
            by_address[a] = by_address.get(a, 0) + v
    if coinjoin:
        sender = _sink("coinjoin", tx)
    elif tx.coinbase:
        sender = _sink("block-reward", tx)
    elif not by_address:
        sender = _sink("no-address", tx)
    else:
        sender = min(by_address, key=lambda a: (-by_address[a], a))
    return [_transfer(tx, sender, address, got, sender)]


def tx_frame(txs: list[UtxoTx]):
    """The transactions as the table graph/resolve.py and graph/coinjoin.py read."""
    import polars as pl

    from ..graph.resolve import script_of_address
    rows = [{"txid": t.txid, "timestamp": t.time.timestamp(),
             "input_addresses": [a for a, _ in t.inputs if a],
             "input_amounts": [v for a, v in t.inputs if a],
             "output_addresses": [a for a, _ in t.outputs if a],
             "output_amounts": [v for a, v in t.outputs if a],
             "fee": t.fee} for t in {t.txid: t for t in txs}.values()]
    schema = {"txid": pl.String, "timestamp": pl.Float64,
              "input_addresses": pl.List(pl.String), "input_amounts": pl.List(pl.Int64),
              "output_addresses": pl.List(pl.String), "output_amounts": pl.List(pl.Int64),
              "fee": pl.Int64}
    df = pl.DataFrame(rows, schema=schema).sort("txid")
    return df.with_columns(
        script_of_address(pl.col("input_addresses").list.first().fill_null("")).alias("script_type"))


def coinjoin_ids(txs: list[UtxoTx]) -> set[str]:
    """Which of these transactions have the shape of a collaborative CoinJoin: the shape
    rule of graph/coinjoin.py with the settings measured on real transactions (see its
    docstring), less the transactions whose equal outputs are dust. On the 7,334 real
    exchange transactions of that measurement the shape alone flagged 6 token transfers
    with n outputs of 546 satoshis each."""
    from ..graph.coinjoin import coinjoin_txids
    if not txs:
        return set()
    by_id = {t.txid: t for t in txs}
    return {txid for txid in coinjoin_txids(tx_frame(txs), MIN_EQUAL, MIN_SHARE)
            if by_id[txid].equal_block()[0] >= MIN_MIX}


def _check(body) -> None:
    if not isinstance(body, list):
        raise ProviderError(f"Esplora: unexpected body {str(body)[:200]}")


class BtcProvider(ChainProvider):
    chain = "bitcoin"
    traceable_assets = ("BTC",)
    newest_first = True         # without `since`, a cut listing is the most recent part
    sink_reason = staticmethod(sink_reason)

    def __init__(self, fetcher: Fetcher, max_pages: int = 40, api: str | None = None):
        self.fetcher, self.max_pages = fetcher, max_pages
        self.api = api or os.environ.get("VASPFUSION_BTC_API") or DEFAULT_API
        if self.api not in ESPLORA:
            raise ValueError(f"unknown Bitcoin API {self.api!r} (known: {', '.join(ESPLORA)})")
        self.base = ESPLORA[self.api]
        fetcher.min_interval.setdefault(self.api, 0.5)
        self._seen: dict[str, UtxoTx] = {}      # every transaction read, for fee_share()
        self._own: str | None = None            # the wallet being traced (trace_from)

    @staticmethod
    def _address(address: str) -> str:
        address = address.strip()
        if not validate(address, "bitcoin"):
            raise InvalidAddress(f"not a Bitcoin address: {address}")
        return address.lower() if address.lower().startswith("bc1") else address

    def trace_from(self, address: str) -> None:
        """Name the wallet being traced: its own multi-address spends are split in
        proportion (see `out_transfers`); nobody else's are."""
        self._own = self._address(address)

    def pages(self, address: str):
        """The address's confirmed transactions, newest first, a page at a time:
        yields (transactions, is this the last page)."""
        address = self._address(address)
        url = f"{self.base}/address/{address}/txs"
        for _ in range(self.max_pages):
            raw = self.fetcher.get_json("bitcoin", address, "both", url, {}, check=_check)
            confirmed = [t for t in raw if (t.get("status") or {}).get("confirmed")]
            txs = [UtxoTx.from_esplora(t) for t in confirmed]
            for t in txs:
                self._seen[t.txid] = t
            last = len(confirmed) < LAST_PAGE_BELOW
            yield txs, last
            if last:
                return
            url = f"{self.base}/address/{address}/txs/chain/{confirmed[-1]['txid']}"

    def txs(self, address: str, pages: int = 1) -> tuple[list[UtxoTx], bool]:
        """The newest `pages` pages of the address's transactions, and whether that is
        known to be its whole history."""
        out: list[UtxoTx] = []
        for i, (txs, last) in enumerate(self.pages(address), 1):
            out += txs
            if last or i >= pages:
                return out, last
        return out, False

    def seen(self, tx_hash: str) -> UtxoTx | None:
        """A transaction this provider has read, by id."""
        return self._seen.get(tx_hash)

    def fee_share(self, address: str, tx_hash: str) -> Decimal:
        """The address's part of the miner fee of a transaction this provider has read."""
        tx = self._seen.get(tx_hash)
        return fee_share(tx, self._address(address)) if tx else Decimal(0)

    def transfers(self, address: str, direction: Direction = "both",
                  since: datetime | None = None, limit: int = 200,
                  asset: str | None = None) -> TransferList:
        address = self._address(address)
        self._check_asset(asset)
        out: list[Transfer] = []
        reached = False     # paged back to the start of the history, or to before `since`
        for txs, last in self.pages(address):
            mixed = coinjoin_ids(txs)
            for tx in txs:
                if direction != "in":
                    out += out_transfers(tx, address, tx.txid in mixed, own=address == self._own)
                if direction != "out":
                    out += in_transfers(tx, address, tx.txid in mixed)
            oldest = min((t.time for t in txs), default=None)
            if last or (since is not None and oldest is not None and oldest < since):
                reached = True
                break
            if since is None and len(out) >= limit:
                break
        rows = sort_transfers(out)
        if since is not None:
            if not reached:
                # the pages read are the NEWEST ones: the transfers right after `since`
                # are in the part that was not read, and these are not a substitute
                return TransferList([], complete=False)
            rows = [t for t in rows if t.block_time >= since]
            return TransferList(rows[:limit], complete=len(rows) <= limit)
        return TransferList(rows[-limit:] if limit else [],
                            complete=reached and len(rows) <= limit)
