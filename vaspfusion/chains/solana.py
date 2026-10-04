"""Solana through Helius' parsed transaction history (HELIUS_API_KEY, free plan).

`GET /v0/addresses/{address}/transactions` returns each transaction already broken
into native SOL transfers and SPL token transfers (measured 5 Oct 2026):

* at most 100 transactions a page; `sort-order=asc` gives oldest first, `gte-time`
  is `since`, and `after-signature` pages forward;
* an SPL transfer moves between *token accounts*, which mean nothing to an
  investigator. Helius also names the wallets that own them (`fromUserAccount`,
  `toUserAccount`), and those are what a Transfer holds;
* `feePayer` is the first signer; a failed transaction has `transactionError` set
  and is dropped.

One listing carries every asset, so the asset and direction filters are applied here
and a page is cached once whatever was asked of it. A transaction may move value
between other parties too (a swap, a batch payout): only the transfers that touch
the address are returned. SOL sent to a token account of the same transaction is the
rent that opens the account, not a payment, and is left out.

Token amounts arrive as JSON numbers. USDT and USDC (6 decimals, checked with
`getTokenSupply`) are rounded to their 6 places; any other token is named `?@mint`
(the listing has no symbol) and its amount is as exact as a double.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .addresses import validate
from .base import (CacheMiss, ChainProvider, Direction, InvalidAddress, ProviderError,
                   Retryable, Transfer, TransferList, UnsupportedChain, sort_transfers,
                   utc_from_s)
from .cache import Fetcher
from .http import api_key

HELIUS = "https://api.helius.xyz/v0/addresses/{address}/transactions"
PAGE_MAX = 100                  # limit=101 is refused
NATIVE = "SOL"
LAMPORTS = 9
# mint -> (symbol, decimals)
STABLECOINS: dict[str, tuple[str, int]] = {
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": ("USDT", 6),
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": ("USDC", 6),
}


def _check(body) -> None:
    if isinstance(body, list):
        return
    text = str(body.get("error") if isinstance(body, dict) else body)
    if "rate limit" in text.lower() or "too many requests" in text.lower():
        raise Retryable(text)
    raise ProviderError(f"Helius API error: {text[:200]}")


class SolanaProvider(ChainProvider):
    chain = "solana"
    traceable_assets = ("USDT", "USDC", NATIVE)
    # Opening a token account costs about 0.002 SOL and a transfer 0.000005; more than
    # 0.1 SOL is a payment in SOL, not a fee top-up.
    top_up_range = (None, Decimal("0.1"))

    def __init__(self, fetcher: Fetcher, page_size: int = PAGE_MAX, max_pages: int = 10):
        self.fetcher = fetcher
        self.page_size, self.max_pages = min(page_size, PAGE_MAX), max_pages
        self.key = api_key("HELIUS_API_KEY")
        # 14 calls in 8 s were answered and the 15th refused (free plan)
        fetcher.min_interval.setdefault("api.helius.xyz", 0.6)

    def transfers(self, address: str, direction: Direction = "both",
                  since: datetime | None = None, limit: int = 200,
                  asset: str | None = None) -> TransferList:
        address = address.strip()
        if not validate(address, "solana"):
            raise InvalidAddress(f"not a Solana address: {address}")
        self._check_asset(asset)
        rows: list[Transfer] = []
        after, ended = None, False
        for _ in range(self.max_pages):
            page = self._page(address, since, after)
            for tx in page:
                for t in self._parse(tx, address):
                    if (asset is None or t.asset == asset) and \
                            (direction == "both" or t.direction_for(address) == direction):
                        rows.append(t)
            if len(page) < self.page_size:
                ended = True
                break
            after = page[-1]["signature"]
            if len(rows) >= limit:
                break
        return TransferList(sort_transfers(rows)[:limit], complete=ended and len(rows) <= limit)

    def _page(self, address: str, since: datetime | None, after: str | None) -> list[dict]:
        params: dict = {"limit": self.page_size, "sort-order": "asc"}
        if since is not None:
            params["gte-time"] = int(since.timestamp())
        if after:
            params["after-signature"] = after
        if self.key:
            params["api-key"] = self.key
        try:
            # the request is the same for every direction and asset: stored once
            return self.fetcher.get_json(self.chain, address, "both",
                                         HELIUS.format(address=address), params, check=_check)
        except CacheMiss:
            raise
        except ProviderError as e:
            if self.key:
                raise
            raise UnsupportedChain(
                f"solana needs HELIUS_API_KEY (Helius' free plan serves it; without a key "
                f"Helius answered: {e})") from e

    def _parse(self, tx: dict, address: str) -> list[Transfer]:
        if tx.get("transactionError"):
            return []
        when, sig, payer = utc_from_s(tx["timestamp"]), tx["signature"], tx.get("feePayer")
        tokens = tx.get("tokenTransfers") or []
        token_accounts = {t.get(k) for t in tokens for k in ("fromTokenAccount", "toTokenAccount")}
        out: list[Transfer] = []
        for t in tx.get("nativeTransfers") or []:
            a, b, lamports = t.get("fromUserAccount"), t.get("toUserAccount"), t.get("amount") or 0
            if not a or not b or a == b or address not in (a, b) or lamports <= 0 \
                    or a in token_accounts or b in token_accounts:
                continue
            out.append(Transfer(self.chain, sig, when, a, b, NATIVE,
                                Decimal(int(lamports)).scaleb(-LAMPORTS), None, payer))
        for t in tokens:
            a, b, mint = t.get("fromUserAccount"), t.get("toUserAccount"), t.get("mint")
            if not a or not b or a == b or address not in (a, b) or not mint:
                continue
            amount = Decimal(repr(t.get("tokenAmount") or 0))
            known = STABLECOINS.get(mint)
            if known:
                amount = amount.quantize(Decimal(1).scaleb(-known[1]))
            if amount <= 0:
                continue
            out.append(Transfer(self.chain, sig, when, a, b, known[0] if known else f"?@{mint}",
                                amount, amount if known else None, payer, asset_contract=mint))
        return out
