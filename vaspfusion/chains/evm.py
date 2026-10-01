"""EVM chains through the Etherscan-compatible account API (`txlist` + `tokentx`).

Two backends speak the same API:
* Etherscan v2 (`/v2/api?chainid=`), used when ETHERSCAN_API_KEY is set. Its
  free plan answers for ethereum, polygon and arbitrum only; BSC, Base, OP and
  Avalanche return "Free API access is not supported for this chain"
  (measured 1 Oct 2026), which becomes `UnsupportedChain`.
* Blockscout (keyless), used without a key and for base / optimism.

`txlist` gives native-coin transfers (successful, value > 0; the sender pays gas),
`tokentx` ERC-20 transfers (the gas payer is not in that response). `since` is
turned into a start block with `getblocknobytime`. Direction is filtered here, as
the API returns both. Etherscan serves at most 10,000 rows per query window, so
`limit` is capped there.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .addresses import validate
from .base import (ChainProvider, Direction, InvalidAddress, ProviderError, Retryable,
                   Transfer, UnsupportedChain, sort_transfers, utc_from_s)
from .cache import Fetcher
from .http import api_key

ETHERSCAN = "https://api.etherscan.io/v2/api"
MAX_WINDOW = 10_000

# chain -> backends in order of preference: ("etherscan", chainid) | ("blockscout", api url)
BACKENDS: dict[str, tuple[tuple[str, object], ...]] = {
    "ethereum": (("etherscan", 1), ("blockscout", "https://eth.blockscout.com/api")),
    "polygon": (("etherscan", 137), ("blockscout", "https://polygon.blockscout.com/api")),
    "arbitrum": (("etherscan", 42161), ("blockscout", "https://arbitrum.blockscout.com/api")),
    "base": (("blockscout", "https://base.blockscout.com/api"),),
    "optimism": (("blockscout", "https://explorer.optimism.io/api"),),
    "bsc": (("etherscan", 56),),
}
NATIVE = {"ethereum": "ETH", "polygon": "POL", "arbitrum": "ETH", "base": "ETH",
          "optimism": "ETH", "bsc": "BNB"}
# USD stablecoin contracts (lowercase). Anything else is named SYMBOL@contract.
STABLECOINS: dict[str, dict[str, str]] = {
    "ethereum": {"0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
                 "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC"},
    "polygon": {"0xc2132d05d31c914a87c6611c10748aeb04b58e8f": "USDT",
                "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": "USDC",
                "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": "USDC.e"},
    "arbitrum": {"0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9": "USDT",
                 "0xaf88d065e77c8cc2239327c5edb3a432268e5831": "USDC"},
    "base": {"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC"},
    "optimism": {"0x94b008aa00579c1307b0ef2c499ad98a8ce58e58": "USDT",
                 "0x0b2c639c533813f4aa9d7837caf62653d097ff85": "USDC"},
    "bsc": {"0x55d398326f99059ff775485246999027b3197955": "USDT",
            "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": "USDC"},
}
_EMPTY = ("no transactions found", "no token transfers found", "no records found")


def _check(body) -> None:
    if not isinstance(body, dict):
        raise ProviderError(f"unexpected body: {str(body)[:200]}")
    if str(body.get("status")) == "1":
        return
    msg = str(body.get("message", "")).lower()
    result = body.get("result")
    text = str(result).lower() if isinstance(result, str) else ""
    if msg.startswith(_EMPTY) and not text:
        return
    if "rate limit" in text or "rate limit" in msg:
        raise Retryable(text or msg)
    if "not supported for this chain" in text:
        raise UnsupportedChain(f"Etherscan: {result}")
    raise ProviderError(f"explorer API error: {body.get('message')}: {str(result)[:200]}")


class EvmProvider(ChainProvider):
    def __init__(self, chain: str, fetcher: Fetcher, page_size: int = 1000,
                 max_pages: int = 10, key: str | None = None):
        if chain not in BACKENDS:
            raise UnsupportedChain(f"no EVM backend for {chain}")
        self.chain, self.fetcher = chain, fetcher
        self.page_size, self.max_pages = page_size, max_pages
        self.key = key if key is not None else api_key("ETHERSCAN_API_KEY")
        self.kind, self.target = self._pick_backend()
        if self.kind == "etherscan":
            fetcher.min_interval.setdefault("api.etherscan.io", 0.35)
        else:
            fetcher.min_interval.setdefault(str(self.target).split("/")[2], 0.2)

    def _pick_backend(self) -> tuple[str, object]:
        options = BACKENDS[self.chain]
        for kind, target in options:
            if kind == "blockscout" or self.key:
                return kind, target
        raise UnsupportedChain(f"{self.chain} needs ETHERSCAN_API_KEY on a paid Etherscan plan "
                               "(the free plan and Blockscout do not cover it)")

    def _request(self, params: dict) -> tuple[str, dict]:
        if self.kind == "etherscan":
            return ETHERSCAN, {"chainid": self.target, **params, "apikey": self.key}
        return str(self.target), params

    def _get(self, address: str, direction: str, params: dict):
        url, full = self._request(params)
        return self.fetcher.get_json(self.chain, address, direction, url, full, check=_check)

    def start_block(self, address: str, since: datetime) -> int:
        body = self._get(address, "both", {"module": "block", "action": "getblocknobytime",
                                           "timestamp": int(since.timestamp()),
                                           "closest": "after"})
        r = body["result"]
        return int(r["blockNumber"] if isinstance(r, dict) else r)

    @property
    def traceable_assets(self) -> tuple[str, ...]:
        return (*STABLECOINS[self.chain].values(), NATIVE[self.chain])

    def transfers(self, address: str, direction: Direction = "both",
                  since: datetime | None = None, limit: int = 200,
                  asset: str | None = None) -> list[Transfer]:
        address = address.strip()
        if not validate(address, self.chain):
            raise InvalidAddress(f"not an EVM address: {address}")
        self._check_asset(asset)
        address = address.lower()
        limit = min(limit, MAX_WINDOW)
        start = self.start_block(address, since) if since is not None else 0
        rows: list[Transfer] = []
        if asset in (None, NATIVE[self.chain]):
            rows += self._pages(address, direction, "txlist", start, limit, self._parse_native)
        if asset is None:
            rows += self._pages(address, direction, "tokentx", start, limit, self._parse_token)
        elif asset != NATIVE[self.chain]:
            contract = next(c for c, sym in STABLECOINS[self.chain].items() if sym == asset)
            rows += self._pages(address, direction, "tokentx", start, limit, self._parse_token,
                                {"contractaddress": contract})
        return sort_transfers(rows)[:limit]

    def _pages(self, address, direction, action, start, limit, parse,
               extra: dict | None = None) -> list[Transfer]:
        out: list[Transfer] = []
        for page in range(1, self.max_pages + 1):
            body = self._get(address, direction, {
                "module": "account", "action": action, "address": address,
                "startblock": start, "page": page, "offset": self.page_size, "sort": "asc",
                **(extra or {})})
            result = body.get("result") or []
            for item in result:
                t = parse(item)
                if t is None:
                    continue
                if (direction == "in" and t.to_addr != address) or \
                        (direction == "out" and t.from_addr != address):
                    continue
                out.append(t)
            if len(result) < self.page_size or len(out) >= limit \
                    or (page + 1) * self.page_size > MAX_WINDOW:
                break
        return out

    def _parse_native(self, item: dict) -> Transfer | None:
        value = int(item.get("value") or 0)
        if item.get("isError", "0") != "0" or value == 0 or not item.get("to"):
            return None
        return Transfer(
            chain=self.chain, tx_hash=item["hash"], block_time=utc_from_s(item["timeStamp"]),
            from_addr=item["from"].lower(), to_addr=item["to"].lower(), asset=NATIVE[self.chain],
            amount=Decimal(value).scaleb(-18), amount_usd=None, fee_payer=item["from"].lower())

    def _parse_token(self, item: dict) -> Transfer | None:
        if item.get("tokenID"):  # an NFT row, if a backend mixes them in
            return None
        contract = (item.get("contractAddress") or "").lower()
        decimals = int(item.get("tokenDecimal") or 0)
        amount = Decimal(int(item.get("value") or 0)).scaleb(-decimals)
        symbol = STABLECOINS[self.chain].get(contract)
        return Transfer(
            chain=self.chain, tx_hash=item["hash"], block_time=utc_from_s(item["timeStamp"]),
            from_addr=item["from"].lower(), to_addr=item["to"].lower(),
            asset=symbol or f"{item.get('tokenSymbol') or '?'}@{contract}",
            amount=amount, amount_usd=amount if symbol else None, fee_payer=None,
            asset_contract=contract)
