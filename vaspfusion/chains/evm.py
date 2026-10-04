"""EVM chains through the Etherscan-compatible account API (`txlist` + `tokentx`),
and BNB Chain through Ankr's Advanced API.

Two backends speak the Etherscan API:
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

BNB Chain has no keyless explorer API and Etherscan's free plan refuses it, so it is
read from Ankr (ANKR_API_KEY, free plan; measured 5 Oct 2026): JSON-RPC
`ankr_getTransactionsByAddress` (whole transactions: the native-coin transfers) and
`ankr_getTokenTransfers` (BEP-20), oldest first, `fromTimestamp` for `since`, paged by
`nextPageToken`. Neither call filters by direction or token, so both are filtered
here and a page is cached once whatever was asked of it. Etherscan is used for BNB
Chain only when ETHERSCAN_PAID=1 says the key is on a paid plan: which plan a key is
on cannot be learnt offline, and the backend is part of every cache key.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal

from .addresses import validate
from .base import (CacheMiss, ChainProvider, Direction, InvalidAddress, ProviderError, Retryable,
                   Transfer, TransferList, UnsupportedChain, sort_transfers, utc_from_s)
from .cache import Fetcher
from .http import api_key

ETHERSCAN = "https://api.etherscan.io/v2/api"
ANKR = "https://rpc.ankr.com/multichain"
MAX_WINDOW = 10_000

# chain -> backends in order of preference: ("etherscan", chainid) | ("blockscout", api url)
# | ("etherscan-paid", chainid): Etherscan, only with ETHERSCAN_PAID=1 | ("ankr", its chain name)
BACKENDS: dict[str, tuple[tuple[str, object], ...]] = {
    "ethereum": (("etherscan", 1), ("blockscout", "https://eth.blockscout.com/api")),
    "polygon": (("etherscan", 137), ("blockscout", "https://polygon.blockscout.com/api")),
    "arbitrum": (("etherscan", 42161), ("blockscout", "https://arbitrum.blockscout.com/api")),
    "base": (("blockscout", "https://base.blockscout.com/api"),),
    "optimism": (("blockscout", "https://explorer.optimism.io/api"),),
    "bsc": (("etherscan-paid", 56), ("ankr", "bsc")),
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


def _check_ankr(body) -> None:
    if not isinstance(body, dict):
        raise ProviderError(f"unexpected body: {str(body)[:200]}")
    err = body.get("error")
    if err is None and isinstance(body.get("result"), dict):
        return
    text = str(err.get("message") if isinstance(err, dict) else err)
    if "too many requests" in text.lower() or "rate limit" in text.lower():
        raise Retryable(text)
    raise ProviderError(f"Ankr API error: {text[:200]}")


def _paid_etherscan() -> bool:
    return os.environ.get("ETHERSCAN_PAID", "").strip().lower() in ("1", "true", "yes")


class EvmProvider(ChainProvider):
    # A gas top-up for one token sweep is a few thousandths of a coin (0.0024 ETH in the
    # recorded Bitget sweep). More than 0.1 is a deposit of the coin, not gas.
    top_up_range = (None, Decimal("0.1"))

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
        elif self.kind == "ankr":
            self.ankr_key = api_key("ANKR_API_KEY")
            # 13 calls in 7 s were answered and the 14th refused for 10 s (free plan)
            fetcher.min_interval.setdefault("rpc.ankr.com", 0.6)
        else:
            fetcher.min_interval.setdefault(str(self.target).split("/")[2], 0.2)

    def _pick_backend(self) -> tuple[str, object]:
        options = BACKENDS[self.chain]
        for kind, target in options:
            if kind == "etherscan-paid":
                if self.key and _paid_etherscan():
                    return "etherscan", target
            elif kind in ("blockscout", "ankr") or self.key:
                return kind, target
        raise UnsupportedChain(f"{self.chain} has no backend that answers without a paid "
                               "Etherscan plan")

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
                  asset: str | None = None) -> TransferList:
        address = address.strip()
        if not validate(address, self.chain):
            raise InvalidAddress(f"not an EVM address: {address}")
        self._check_asset(asset)
        address = address.lower()
        limit = min(limit, MAX_WINDOW)
        if self.kind == "ankr":
            return self._ankr_transfers(address, direction, since, limit, asset)
        start = self.start_block(address, since) if since is not None else 0
        rows: list[Transfer] = []
        ended: list[bool] = []          # per listing: did paging reach its end?
        if asset in (None, NATIVE[self.chain]):
            rows += self._pages(address, direction, "txlist", start, limit, self._parse_native,
                                ended)
        if asset is None:
            rows += self._pages(address, direction, "tokentx", start, limit, self._parse_token,
                                ended)
        elif asset != NATIVE[self.chain]:
            contract = next(c for c, sym in STABLECOINS[self.chain].items() if sym == asset)
            rows += self._pages(address, direction, "tokentx", start, limit, self._parse_token,
                                ended, {"contractaddress": contract})
        return TransferList(sort_transfers(rows)[:limit],
                            complete=all(ended) and len(rows) <= limit)

    def _pages(self, address, direction, action, start, limit, parse, ended: list[bool],
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
            if len(result) < self.page_size:
                ended.append(True)
                return out
            if len(out) >= limit or (page + 1) * self.page_size > MAX_WINDOW:
                break
        ended.append(False)             # stopped at `limit`, the page cap or the API window
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

    # ------------------------------------------------------------------ Ankr (BNB Chain)
    def _ankr_transfers(self, address: str, direction: str, since: datetime | None,
                        limit: int, asset: str | None) -> TransferList:
        native = NATIVE[self.chain]
        rows: list[Transfer] = []
        ended: list[bool] = []
        if asset in (None, native):
            rows += self._ankr_pages(address, direction, since, limit, ended,
                                     "ankr_getTransactionsByAddress", "transactions",
                                     self._parse_ankr_native, None)
        if asset != native:
            rows += self._ankr_pages(address, direction, since, limit, ended,
                                     "ankr_getTokenTransfers", "transfers",
                                     self._parse_ankr_token, asset)
        return TransferList(sort_transfers(rows)[:limit],
                            complete=all(ended) and len(rows) <= limit)

    def _ankr_pages(self, address, direction, since, limit, ended: list[bool], method: str,
                    field: str, parse, asset: str | None) -> list[Transfer]:
        out: list[Transfer] = []
        token = ""
        for _ in range(self.max_pages):
            args = {"blockchain": self.target, "address": [address],
                    "pageSize": self.page_size, "descOrder": False}
            if since is not None:
                args["fromTimestamp"] = int(since.timestamp())
            if token:
                args["pageToken"] = token
            result = self._ankr(address, method, args)["result"]
            for item in result.get(field) or []:
                t = parse(item)
                if t is None or (asset is not None and t.asset != asset) or \
                        (direction == "in" and t.to_addr != address) or \
                        (direction == "out" and t.from_addr != address):
                    continue
                out.append(t)
            token = result.get("nextPageToken") or ""
            if not token:
                ended.append(True)
                return out
            if len(out) >= limit:
                break
        ended.append(False)             # stopped at `limit` or the page cap
        return out

    def _ankr(self, address: str, method: str, args: dict) -> dict:
        params = {"method": method,
                  "params": json.dumps(args, sort_keys=True, separators=(",", ":"))}
        try:
            # the request is the same for every direction, so the page is stored once
            return self.fetcher.get_json(self.chain, address, "both", ANKR, params,
                                         check=_check_ankr, rpc=True, secret=self.ankr_key)
        except CacheMiss:
            raise
        except ProviderError as e:
            if self.ankr_key:
                raise
            raise UnsupportedChain(
                f"{self.chain} needs ANKR_API_KEY (Ankr's free plan serves it; without a "
                f"key Ankr answered: {e})") from e

    def _parse_ankr_native(self, item: dict) -> Transfer | None:
        value = int(item.get("value") or "0x0", 16)
        if item.get("status") != "0x1" or value == 0 or not item.get("to"):
            return None
        return Transfer(
            chain=self.chain, tx_hash=item["hash"],
            block_time=utc_from_s(int(item["timestamp"], 16)),
            from_addr=item["from"].lower(), to_addr=item["to"].lower(), asset=NATIVE[self.chain],
            amount=Decimal(value).scaleb(-18), amount_usd=None, fee_payer=item["from"].lower())

    def _parse_ankr_token(self, item: dict) -> Transfer | None:
        contract = (item.get("contractAddress") or "").lower()
        if not contract or not item.get("fromAddress") or not item.get("toAddress"):
            return None
        amount = Decimal(int(item.get("valueRawInteger") or 0)).scaleb(
            -int(item.get("tokenDecimals") or 0))
        symbol = STABLECOINS[self.chain].get(contract)
        return Transfer(
            chain=self.chain, tx_hash=item["transactionHash"],
            block_time=utc_from_s(item["timestamp"]),
            from_addr=item["fromAddress"].lower(), to_addr=item["toAddress"].lower(),
            asset=symbol or f"{item.get('tokenSymbol') or '?'}@{contract}",
            amount=amount, amount_usd=amount if symbol else None, fee_payer=None,
            asset_contract=contract)
