"""Chain adapters: `get_provider(chain).transfers(address, direction, since, limit)`.

Every request goes through a cache-first `Fetcher` (cache.py); OFFLINE=1 serves
from the cache only. See docs/plans/2026-10-01-b2-chain-adapters.md.
"""
from __future__ import annotations

from .addresses import EVM_FAMILY, detect_chain, validate
from .base import (CacheMiss, ChainProvider, Direction, InvalidAddress, ProviderError,
                   Transfer, UnsupportedChain)
from .cache import ChainCache, Fetcher
from .http import UrllibTransport

__all__ = ["CacheMiss", "ChainCache", "ChainProvider", "Direction", "Fetcher", "InvalidAddress",
           "ProviderError", "Transfer", "UnsupportedChain", "default_fetcher", "detect_chain",
           "get_provider", "validate"]


def default_fetcher() -> Fetcher:
    return Fetcher(ChainCache(), UrllibTransport())


def get_provider(chain: str, fetcher: Fetcher | None = None) -> ChainProvider:
    fetcher = fetcher or default_fetcher()
    if chain == "tron":
        from .tron import TronProvider
        return TronProvider(fetcher)
    if chain == "bitcoin":
        from .btc import BtcProvider
        return BtcProvider(fetcher)
    if chain == "solana":
        from .solana import SolanaProvider
        return SolanaProvider(fetcher)
    if chain in EVM_FAMILY:
        from .evm import EvmProvider
        return EvmProvider(chain, fetcher)
    raise UnsupportedChain(f"no adapter for chain {chain!r}")
