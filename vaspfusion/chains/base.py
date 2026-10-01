"""The one shape every chain adapter returns, and the errors they raise.

A `Transfer` is one value movement between two addresses. Tron and EVM transfers
map 1:1 to on-chain transfers; a Bitcoin transaction (many inputs, many outputs)
becomes one Transfer per output, see btc.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

Direction = Literal["in", "out", "both"]
DIRECTIONS = ("in", "out", "both")


class InvalidAddress(ValueError):
    """The string is not a valid address for any supported (or the given) chain."""


class ProviderError(RuntimeError):
    """The upstream API answered with an error we must not retry or cache."""


class Retryable(Exception):
    """A transient upstream failure (rate limit, 5xx); the fetcher backs off and retries."""


class CacheMiss(ProviderError):
    """OFFLINE=1 and the request is not in the cache."""


class UnsupportedChain(ProviderError):
    """The chain is recognised but transfers cannot be fetched for it (yet)."""


@dataclass(frozen=True)
class Transfer:
    chain: str
    tx_hash: str
    block_time: datetime            # timezone-aware UTC
    from_addr: str
    to_addr: str
    asset: str                      # "TRX", "ETH", "USDT", or "SYMBOL@contract" for unknown tokens
    amount: Decimal                 # in whole units (decimals already applied)
    amount_usd: Decimal | None      # only for USD stablecoins; no price feed yet
    fee_payer: str | None           # who paid the network fee, when the API tells us
    asset_contract: str | None = None  # token contract; None for the native coin

    def direction_for(self, address: str) -> str:
        return "out" if self.from_addr == address else "in"

    def to_dict(self) -> dict:
        return {
            "chain": self.chain,
            "tx_hash": self.tx_hash,
            "block_time": self.block_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "from_addr": self.from_addr,
            "to_addr": self.to_addr,
            "asset": self.asset,
            "amount": _dec(self.amount),
            "amount_usd": None if self.amount_usd is None else _dec(self.amount_usd),
            "fee_payer": self.fee_payer,
            "asset_contract": self.asset_contract,
        }


def _dec(d: Decimal) -> str:
    """Plain notation, no exponent, no trailing zeros: Decimal('1.500E+3') -> '1500'."""
    s = format(d, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def sort_transfers(rows: list[Transfer]) -> list[Transfer]:
    """The one canonical order, so a replay prints byte-identical output."""
    return sorted(rows, key=lambda t: (t.block_time, t.tx_hash, t.from_addr, t.to_addr,
                                       t.asset, t.amount))


def utc_from_ms(ms: int | str) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)


def utc_from_s(s: int | str) -> datetime:
    return datetime.fromtimestamp(int(s), tz=timezone.utc)


class ChainProvider(ABC):
    """One adapter per chain family. Adapters never open sockets themselves: every
    request goes through a `Fetcher` (cache.py), which caches and honours OFFLINE=1."""

    chain: str
    # Assets a trace can follow on this chain: USD stablecoins first, the native coin last.
    traceable_assets: tuple[str, ...] = ()

    @abstractmethod
    def transfers(self, address: str, direction: Direction = "both",
                  since: datetime | None = None, limit: int = 200,
                  asset: str | None = None) -> list[Transfer]:
        """Transfers touching `address`, oldest first (see each adapter for paging
        limits), at most `limit`. With `asset` (one of `traceable_assets`) only that
        asset is fetched, so `limit` is not used up by anything else."""

    def _check_asset(self, asset: str | None) -> None:
        if asset is not None and asset not in self.traceable_assets:
            raise ValueError(f"{self.chain} cannot fetch asset {asset!r} on its own "
                             f"(traceable: {', '.join(self.traceable_assets)})")

    @staticmethod
    def detect_chain(address: str) -> str:
        from .addresses import detect_chain
        return detect_chain(address)
