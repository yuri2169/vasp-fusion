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


@dataclass(frozen=True)
class GasEvent:
    """Someone else covering an address's network fee: the signal exchanges leave on
    their deposit addresses just before a sweep (B4's gas-payer rule)."""
    time: datetime                  # timezone-aware UTC
    payer: str
    kind: str                       # "energy" | "bandwidth" (Tron delegation) | "native" (top-up)
    tx_hash: str
    amount: Decimal | None = None   # native units for a top-up, else None


class GasList(list):
    """What `gas_events()` returns: a list, plus whether the listing behind it was read
    to its end. False: later payers may be missing."""

    def __init__(self, rows=(), complete: bool = True):
        super().__init__(rows)
        self.complete = complete


class TransferList(list):
    """What `transfers()` returns: a list, plus whether it is the whole answer.

    `complete` is True only when the adapter reached the end of every listing it
    paged and returned every row it found. It is False when paging stopped at the
    page cap or the rows were cut to `limit`: then "no further transfers" is not
    something the caller may conclude."""

    def __init__(self, rows=(), complete: bool = True):
        super().__init__(rows)
        self.complete = complete


def qualify(chain: str, address: str, home: str) -> str:
    """The id of a wallet in a trace that started on `home`. On the home chain it is the
    plain address. On any other chain it is `chain:address`: an EVM address is the same
    string on every EVM chain, so the address alone would make two wallets one."""
    return address if chain == home else f"{chain}:{address}"


def split_id(wallet_id: str, home: str) -> tuple[str, str]:
    """(chain, address) of a wallet id. No address format here contains a colon."""
    chain, sep, address = wallet_id.partition(":")
    return (chain, address) if sep else (home, wallet_id)


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

    # A native transfer in this range (whole coins) is a fee top-up; anything larger is
    # a deposit of the coin itself, not gas. None = no bound.
    top_up_range: tuple[Decimal | None, Decimal | None] = (None, None)

    def _is_top_up(self, amount: Decimal) -> bool:
        low, high = self.top_up_range
        return amount > 0 and (low is None or amount >= low) and (high is None or amount <= high)

    def gas_events(self, address: str, since: datetime | None = None,
                   limit: int = 200) -> "GasList":
        """Who covered `address`'s network fee. The default is what every chain has:
        native-coin top-ups from someone else (an exchange funding a deposit address
        before it sweeps it). Tron adds energy delegations, see tron.py."""
        native = self.traceable_assets[-1]
        rows = self.transfers(address, "both", since=since, limit=limit, asset=native)
        return GasList(
            [GasEvent(t.block_time, t.from_addr, "native", t.tx_hash, t.amount)
             for t in rows if t.to_addr != t.from_addr and t.to_addr.lower() == address.lower()
             and self._is_top_up(t.amount)],
            complete=getattr(rows, "complete", True))

    def _check_asset(self, asset: str | None) -> None:
        if asset is not None and asset not in self.traceable_assets:
            raise ValueError(f"{self.chain} cannot fetch asset {asset!r} on its own "
                             f"(traceable: {', '.join(self.traceable_assets)})")

    @staticmethod
    def detect_chain(address: str) -> str:
        from .addresses import detect_chain
        return detect_chain(address)
