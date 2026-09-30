"""Solana: address check only. Transfers arrive in the F-finale phase."""
from __future__ import annotations

from datetime import datetime

from .addresses import validate
from .base import ChainProvider, Direction, InvalidAddress, Transfer, UnsupportedChain


class SolanaProvider(ChainProvider):
    chain = "solana"

    def __init__(self, fetcher=None):
        self.fetcher = fetcher

    def transfers(self, address: str, direction: Direction = "both",
                  since: datetime | None = None, limit: int = 200) -> list[Transfer]:
        if not validate(address, "solana"):
            raise InvalidAddress(f"not a Solana address: {address}")
        raise UnsupportedChain("Solana transfers are not implemented yet (planned for F-finale); "
                               "the address itself is valid")
