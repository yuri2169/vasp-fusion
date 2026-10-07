"""Chain adapters: `get_provider(chain).transfers(address, direction, since, limit)`.

Every request goes through a cache-first `Fetcher` (cache.py); OFFLINE=1 serves
from the cache only.
"""
from __future__ import annotations

from .addresses import EVM_FAMILY, detect_chain, validate
from .base import (CacheMiss, ChainProvider, Direction, InvalidAddress, ProviderError,
                   Transfer, UnsupportedChain)
from .cache import ChainCache, Fetcher, LayeredCache
from .http import UrllibTransport

from . import cache  # noqa: F401

__all__ = ["CacheMiss", "ChainCache", "ChainProvider", "Direction", "Fetcher", "InvalidAddress",
           "LayeredCache", "ProviderError", "Transfer", "UnsupportedChain", "UrllibTransport", "cache_only_fetcher", "default_fetcher",
           "detect_chain", "get_provider", "validate"]


def default_fetcher() -> Fetcher:
    """Cache first, then the chain APIs, paced by the limiter every worker shares. With
    OFFLINE=1 nothing can be written, so the cache is opened for a replay."""
    if cache.offline_mode():
        return Fetcher(ChainCache(read_only=True), UrllibTransport())
    from .ratelimit import RateLimiter
    return Fetcher(ChainCache(), UrllibTransport(), limiter=RateLimiter())


def cache_only_fetcher(path=None) -> Fetcher:
    """Reads the cache and nothing else, whatever OFFLINE says (`verify`)."""
    return Fetcher(ChainCache(path, read_only=True), None, offline=True)


def get_provider(chain: str, fetcher: Fetcher | None = None, **opts) -> ChainProvider:
    """`opts` are paging options (page_size, max_pages, key); each adapter takes the
    ones it has and the rest are dropped, so one call site can serve every chain."""
    fetcher = fetcher or default_fetcher()

    def only(*names: str) -> dict:
        return {k: opts[k] for k in names if opts.get(k) is not None}

    if chain == "tron":
        from .tron import TronProvider
        return TronProvider(fetcher, **only("page_size", "max_pages", "key"))
    if chain == "bitcoin":
        from .btc import BtcProvider
        return BtcProvider(fetcher, **only("max_pages"))
    if chain == "solana":
        from .solana import SolanaProvider
        return SolanaProvider(fetcher, **only("page_size", "max_pages"))
    if chain in EVM_FAMILY:
        from .evm import EvmProvider
        return EvmProvider(chain, fetcher, **only("page_size", "max_pages", "key"))
    raise UnsupportedChain(f"no adapter for chain {chain!r}")
