"""Toy UTXO transactions for the cluster and trace tests.

Placeholder names ("S", "D", "HOT"), never real-looking addresses; each transaction is
hand-written to exercise one rule. The provider answers like chains/btc.py's, through
the same out_transfers / in_transfers / fee_share functions the real adapter uses.
"""
from datetime import datetime, timedelta, timezone

from vaspfusion.chains.base import ProviderError, TransferList, sort_transfers
from vaspfusion.chains.btc import (UtxoTx, coinjoin_ids, fee_share, in_transfers, out_transfers,
                                   sink_reason)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def utx(n, inputs, outputs, minute=0, coinbase=False) -> UtxoTx:
    """Transaction number `n` at T0 + `minute`: inputs and outputs are (name, satoshis)."""
    return UtxoTx(txid=f"tx{n}", time=T0 + timedelta(minutes=minute),
                  inputs=tuple(inputs), outputs=tuple(outputs), coinbase=coinbase)


class ToyUtxoProvider:
    chain = "bitcoin"
    traceable_assets = ("BTC",)
    newest_first = True
    sink_reason = staticmethod(sink_reason)

    def __init__(self, txs, fail=(), unread=()):
        self.all = sorted(txs, key=lambda t: (t.time, t.txid))
        self._seen = {t.txid: t for t in txs}
        self.mixed = coinjoin_ids(list(txs))
        self.fail = set(fail)
        self.unread = set(unread)       # wallets too busy to read back to a `since`
        self.own = None
        self.calls: list[tuple] = []

    def trace_from(self, address):
        self.own = address

    def seen(self, tx_hash):
        return self._seen.get(tx_hash)

    def txs(self, address, pages=1):
        self.calls.append(("txs", address))
        if address in self.fail:
            raise ProviderError(f"upstream failed for {address}")
        return [t for t in self.all if address in t.input_addresses or t.paid_to(address)], True

    def transfers(self, address, direction="both", since=None, limit=200, asset=None):
        self.calls.append(("transfers", address, direction))
        if address in self.fail:
            raise ProviderError(f"upstream failed for {address}")
        if since is not None and address in self.unread:
            return TransferList([], complete=False)
        rows = []
        for t in self.all:
            if direction != "in":
                rows += out_transfers(t, address, t.txid in self.mixed, own=address == self.own)
            if direction != "out":
                rows += in_transfers(t, address, t.txid in self.mixed)
        rows = sort_transfers(rows)
        if since is not None:
            rows = [t for t in rows if t.block_time >= since]
        return TransferList(rows[:limit], complete=len(rows) <= limit)

    def fee_share(self, address, tx_hash):
        return fee_share(self._seen[tx_hash], address)
