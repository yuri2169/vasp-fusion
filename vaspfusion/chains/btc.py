"""Bitcoin, basic: mempool.space address history, one Transfer per output.

`/api/address/{a}/txs` returns the newest confirmed transactions plus any
unconfirmed ones; `/txs/chain/{last_txid}` pages further back. The first page
held 50 confirmed transactions when measured (1 Oct 2026; the docs say 25), so a
page with fewer than 25 is taken as the last one rather than trusting a size.
Unconfirmed transactions are skipped (they have no block time and would break a
deterministic replay).

A transaction is outbound when the address funds one of its inputs: each output
to another address is a Transfer (outputs back to the address are change). It is
inbound otherwise: each output paying the address is a Transfer whose sender is
the first input address. Grouping all inputs into one owner is common-input
clustering, which B5 does properly.

The API is newest-first only. With `since`, pages are followed back to `since`
and the earliest `limit` transfers are returned; without it, the most recent
`limit`. `max_pages` bounds both.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .addresses import validate
from .base import (ChainProvider, Direction, InvalidAddress, ProviderError, Transfer,
                   TransferList, sort_transfers, utc_from_s)
from .cache import Fetcher

BASE = "https://mempool.space/api"
HOST = "mempool.space"
LAST_PAGE_BELOW = 25


def _check(body) -> None:
    if not isinstance(body, list):
        raise ProviderError(f"mempool.space: unexpected body {str(body)[:200]}")


class BtcProvider(ChainProvider):
    chain = "bitcoin"
    traceable_assets = ("BTC",)

    def __init__(self, fetcher: Fetcher, max_pages: int = 40):
        self.fetcher, self.max_pages = fetcher, max_pages
        fetcher.min_interval.setdefault(HOST, 0.5)

    def transfers(self, address: str, direction: Direction = "both",
                  since: datetime | None = None, limit: int = 200,
                  asset: str | None = None) -> TransferList:
        address = address.strip()
        if not validate(address, "bitcoin"):
            raise InvalidAddress(f"not a Bitcoin address: {address}")
        self._check_asset(asset)
        if address.lower().startswith("bc1"):
            address = address.lower()
        out: list[Transfer] = []
        reached = False     # paged back to the start of the history, or to before `since`
        url = f"{BASE}/address/{address}/txs"
        for _ in range(self.max_pages):
            txs = self.fetcher.get_json("bitcoin", address, "both", url, {}, check=_check)
            confirmed = [t for t in txs if (t.get("status") or {}).get("confirmed")]
            for tx in confirmed:
                out += [t for t in self._parse(tx, address)
                        if direction == "both" or t.direction_for(address) == direction]
            oldest = min((t["status"]["block_time"] for t in confirmed), default=None)
            if len(confirmed) < LAST_PAGE_BELOW:
                reached = True
                break
            if since is not None and oldest is not None and oldest < since.timestamp():
                reached = True
                break
            if since is None and len(out) >= limit:
                break
            url = f"{BASE}/address/{address}/txs/chain/{confirmed[-1]['txid']}"
        rows = sort_transfers(out)
        if since is not None:
            rows = [t for t in rows if t.block_time >= since]
            return TransferList(rows[:limit], complete=reached and len(rows) <= limit)
        return TransferList(rows[-limit:] if limit else [],
                            complete=reached and len(rows) <= limit)

    @staticmethod
    def _parse(tx: dict, address: str) -> list[Transfer]:
        when = utc_from_s(tx["status"]["block_time"])
        inputs = [(v.get("prevout") or {}).get("scriptpubkey_address") for v in tx.get("vin", [])]
        outputs = [(o.get("scriptpubkey_address"), int(o.get("value") or 0))
                   for o in tx.get("vout", [])]
        rows = []
        if address in inputs:
            for to, sats in outputs:
                if to and to != address and sats:
                    rows.append(Transfer("bitcoin", tx["txid"], when, address, to, "BTC",
                                         Decimal(sats).scaleb(-8), None, address))
        else:
            sender = next((a for a in inputs if a), "coinbase")
            for to, sats in outputs:
                if to == address and sats:
                    rows.append(Transfer("bitcoin", tx["txid"], when, sender, address, "BTC",
                                         Decimal(sats).scaleb(-8), None, sender))
        return rows
