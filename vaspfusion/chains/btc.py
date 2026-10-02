"""Bitcoin: an address's history from an Esplora API, as honest address-to-address transfers.

A Bitcoin transaction has many inputs and many outputs and says nothing about which
input paid which output. Two rules turn it into Transfers, and neither guesses:

* OUTBOUND, pro rata. An address that put in `v` of the transaction's `V` input value
  sent each output `v / V` of that output's value (rounded down to a satoshi). Outputs
  that go back to one of the transaction's own input addresses are change and are not
  transfers. The miner fee is the remainder: `fee_share()` gives the address's part.
* INBOUND, one row per transaction: what the transaction paid the address, from the
  input address that put in the most (ties: the smaller string). Under common-input
  ownership every input belongs to that same sender; vaspfusion/cluster.py reads them all.

A CoinJoin-shaped transaction (graph/coinjoin.py) is the exception. Its inputs belong
to different people, so a pro-rata share would hand the address other people's outputs.
It becomes one Transfer into the sink `coinjoin:<txid>`; the trace stops there.

Outputs with no address form (OP_RETURN, bare multisig, pay-to-pubkey) are not followed.

BACKENDS. blockstream.info and mempool.space serve the same Esplora API.
`/address/{a}/txs` returns the newest confirmed transactions plus any unconfirmed ones;
`/txs/chain/{last_txid}` pages further back. The first page held 50 confirmed
transactions when measured (1 Oct 2026; the docs say 25), so a page with fewer than 25
is taken as the last one rather than trusting a size. Unconfirmed transactions are
skipped (no block time; they would break a deterministic replay). The backend is part
of every request and so of every cache key: a replay needs the backend it was recorded
from (`VASPFUSION_BTC_API`, default blockstream.info).

The API is newest-first only. With `since`, pages are followed back to `since` and the
earliest `limit` transfers are returned; without it, the most recent `limit`.
`max_pages` bounds both.
"""
from __future__ import annotations

import os
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
COINJOIN_SINK = "coinjoin:"
MIN_MIX = 10_000    # satoshis: equal outputs smaller than this are dust, not a mix
MIN_EQUAL = 5       # equal-value outputs a CoinJoin has at least (Whirlpool has exactly 5)
MIN_SHARE = 0.25    # ... and their part of all outputs (real Wasabi 1.x rounds: 26% to 51%)
COINBASE = "coinbase"


@dataclass(frozen=True)
class UtxoTx:
    txid: str
    time: datetime                                  # block time, UTC
    inputs: tuple[tuple[str | None, int], ...]      # (address, satoshis) per input
    outputs: tuple[tuple[str | None, int], ...]     # (address, satoshis) per output

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

    @classmethod
    def from_esplora(cls, tx: dict) -> "UtxoTx":
        ins = tuple(((v.get("prevout") or {}).get("scriptpubkey_address"),
                     int((v.get("prevout") or {}).get("value") or 0)) for v in tx.get("vin", []))
        outs = tuple((o.get("scriptpubkey_address"), int(o.get("value") or 0))
                     for o in tx.get("vout", []))
        return cls(tx["txid"], utc_from_s(tx["status"]["block_time"]), ins, outs)


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


def out_transfers(tx: UtxoTx, address: str, coinjoin: bool = False) -> list[Transfer]:
    """What `address` sent in `tx` (see the module docstring)."""
    shares, _ = _shares(tx, address)
    if coinjoin:
        left = sum(shares.values())
        return [_transfer(tx, address, COINJOIN_SINK + tx.txid, left, address)] if left else []
    own = set(tx.input_addresses)
    return [_transfer(tx, address, to, value, address)
            for to, value in shares.items() if to and to not in own and value]


def in_transfers(tx: UtxoTx, address: str, coinjoin: bool = False) -> list[Transfer]:
    """What `tx` paid `address`, unless the address is one of its own inputs (change)."""
    got = tx.paid_to(address)
    if not got or tx.put_in(address) or address in tx.input_addresses:
        return []
    if coinjoin:
        sender = COINJOIN_SINK + tx.txid
    else:
        by_address: dict[str, int] = {}
        for a, v in tx.inputs:
            if a:
                by_address[a] = by_address.get(a, 0) + v
        sender = min(by_address, key=lambda a: (-by_address[a], a)) if by_address else COINBASE
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
    from collections import Counter

    from ..graph.coinjoin import coinjoin_txids
    if not txs:
        return set()
    by_id = {t.txid: t for t in txs}
    return {txid for txid in coinjoin_txids(tx_frame(txs), MIN_EQUAL, MIN_SHARE)
            if Counter(v for a, v in by_id[txid].outputs if a).most_common(1)[0][0] >= MIN_MIX}


def _check(body) -> None:
    if not isinstance(body, list):
        raise ProviderError(f"Esplora: unexpected body {str(body)[:200]}")


class BtcProvider(ChainProvider):
    chain = "bitcoin"
    traceable_assets = ("BTC",)
    newest_first = True         # without `since`, a cut listing is the most recent part

    def __init__(self, fetcher: Fetcher, max_pages: int = 40, api: str | None = None):
        self.fetcher, self.max_pages = fetcher, max_pages
        self.api = api or os.environ.get("VASPFUSION_BTC_API") or DEFAULT_API
        if self.api not in ESPLORA:
            raise ValueError(f"unknown Bitcoin API {self.api!r} (known: {', '.join(ESPLORA)})")
        self.base = ESPLORA[self.api]
        fetcher.min_interval.setdefault(self.api, 0.5)
        self._seen: dict[str, UtxoTx] = {}      # every transaction read, for fee_share()

    @staticmethod
    def _address(address: str) -> str:
        address = address.strip()
        if not validate(address, "bitcoin"):
            raise InvalidAddress(f"not a Bitcoin address: {address}")
        return address.lower() if address.lower().startswith("bc1") else address

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
        its whole history."""
        out: list[UtxoTx] = []
        for i, (txs, last) in enumerate(self.pages(address), 1):
            out += txs
            if last or i >= pages:
                return out, last
        return out, False

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
                    out += out_transfers(tx, address, tx.txid in mixed)
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
            rows = [t for t in rows if t.block_time >= since]
            return TransferList(rows[:limit], complete=reached and len(rows) <= limit)
        return TransferList(rows[-limit:] if limit else [],
                            complete=reached and len(rows) <= limit)
