"""Tron via TronGrid v1 (USDT-TRC20 first, plus native TRX).

Endpoints (both page with `meta.fingerprint`):
* /v1/accounts/{a}/transactions/trc20: TRC-20 Transfer events, filtered to the
  token contracts in `tokens` (USDT by default). Filtering by contract is also
  what drops fake-"USDT" address-poisoning tokens.
* /v1/accounts/{a}/transactions: raw transactions; only successful
  TransferContract (TRX) rows become Transfers. Amounts are in sun (1e-6 TRX).

Direction uses TronGrid's own only_to / only_from, and `since` its min_timestamp,
so paging never downloads rows it would throw away.

fee_payer = the transaction signer (owner_address), who pays bandwidth/energy.
For TRX that is the sender. The TRC-20 endpoint does not carry it, but the raw
listing also returns the TriggerSmartContract call behind each USDT transfer, so
the signer is copied over by txID when both listings reached that transaction;
otherwise it stays None (B4 resolves the rest). A signer that is not the token
sender is the sweep / gas-station pattern B4 looks for.

Key: TRONGRID_API_KEY (optional) as the TRON-PRO-API-KEY header.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from .addresses import tron_hex_to_base58, validate
from .base import (ChainProvider, Direction, InvalidAddress, ProviderError, Transfer,
                   sort_transfers, utc_from_ms)
from .cache import Fetcher
from .http import api_key

BASE = "https://api.trongrid.io"
HOST = "api.trongrid.io"
USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDC = "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8"
STABLECOINS = {USDT: "USDT", USDC: "USDC"}


def _check(body) -> None:
    if not isinstance(body, dict) or body.get("success") is not True:
        err = body.get("error") if isinstance(body, dict) else str(body)[:200]
        raise ProviderError(f"TronGrid error: {err}")


class TronProvider(ChainProvider):
    chain = "tron"

    def __init__(self, fetcher: Fetcher, page_size: int = 200, max_pages: int = 50,
                 tokens: tuple[str, ...] | None = (USDT,), key: str | None = None):
        self.fetcher = fetcher
        self.page_size, self.max_pages = page_size, max_pages
        self.tokens = tokens
        self.key = key if key is not None else api_key("TRONGRID_API_KEY")
        fetcher.min_interval.setdefault(HOST, 0.1 if self.key else 1.0)

    def transfers(self, address: str, direction: Direction = "both",
                  since: datetime | None = None, limit: int = 200) -> list[Transfer]:
        address = address.strip()
        if not validate(address, "tron"):
            raise InvalidAddress(f"not a Tron address: {address}")
        self._signers: dict[str, str] = {}
        rows: list[Transfer] = []
        for token in (self.tokens if self.tokens is not None else (None,)):
            extra = {"contract_address": token} if token else {}
            rows += self._pages(f"{BASE}/v1/accounts/{address}/transactions/trc20", address,
                                direction, since, limit, extra, self._parse_trc20)
        rows += self._pages(f"{BASE}/v1/accounts/{address}/transactions", address,
                            direction, since, limit, {}, self._parse_trx)
        rows = [replace(t, fee_payer=self._signers[t.tx_hash])
                if t.fee_payer is None and t.tx_hash in self._signers else t for t in rows]
        return sort_transfers(rows)[:limit]

    # ------------------------------------------------------------------ paging
    def _pages(self, url, address, direction, since, limit, extra, parse) -> list[Transfer]:
        params = {"limit": self.page_size, "only_confirmed": "true",
                  "order_by": "block_timestamp,asc", **extra}
        if since is not None:
            params["min_timestamp"] = int(since.timestamp() * 1000)
        if direction == "in":
            params["only_to"] = "true"
        elif direction == "out":
            params["only_from"] = "true"
        headers = {"TRON-PRO-API-KEY": self.key} if self.key else {}
        out: list[Transfer] = []
        for _ in range(self.max_pages):
            body = self.fetcher.get_json("tron", address, direction, url, params, headers,
                                         check=_check)
            data = body.get("data") or []
            out += [t for item in data if (t := parse(item)) is not None
                    and address in (t.from_addr, t.to_addr)]
            fp = (body.get("meta") or {}).get("fingerprint")
            if not fp or len(data) < self.page_size or len(out) >= limit:
                break
            params = {**params, "fingerprint": fp}
        return out

    # ------------------------------------------------------------------ parsing
    @staticmethod
    def _parse_trc20(item: dict) -> Transfer | None:
        if item.get("type") != "Transfer":
            return None
        info = item.get("token_info") or {}
        contract = info.get("address")
        decimals = int(info.get("decimals") or 0)
        amount = Decimal(item["value"]).scaleb(-decimals)
        symbol = STABLECOINS.get(contract)
        return Transfer(
            chain="tron", tx_hash=item["transaction_id"],
            block_time=utc_from_ms(item["block_timestamp"]),
            from_addr=item["from"], to_addr=item["to"],
            asset=symbol or f"{info.get('symbol') or '?'}@{contract}",
            amount=amount, amount_usd=amount if symbol else None,
            fee_payer=None, asset_contract=contract)

    def _parse_trx(self, item: dict) -> Transfer | None:
        ret = (item.get("ret") or [{}])[0]
        contracts = (item.get("raw_data") or {}).get("contract") or []
        if contracts and contracts[0].get("type") == "TriggerSmartContract":
            owner = contracts[0]["parameter"]["value"].get("owner_address")
            if owner:
                self._signers[item["txID"]] = tron_hex_to_base58(owner)
        if not contracts or contracts[0].get("type") != "TransferContract" \
                or ret.get("contractRet") != "SUCCESS":
            return None
        v = contracts[0]["parameter"]["value"]
        owner = tron_hex_to_base58(v["owner_address"])
        return Transfer(
            chain="tron", tx_hash=item["txID"], block_time=utc_from_ms(item["block_timestamp"]),
            from_addr=owner, to_addr=tron_hex_to_base58(v["to_address"]), asset="TRX",
            amount=Decimal(int(v["amount"])).scaleb(-6), amount_usd=None, fee_payer=owner)
