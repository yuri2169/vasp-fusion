"""USDT's freeze list, read from the two token contracts themselves.

Tether's USDT contract (TetherToken, on Tron `TR7NHq…gjLj6t` and Ethereum `0xdac1…1ec7`)
keeps a blacklist: an address on it cannot send the token. The contract announces each
change as an event, `AddedBlackList(address _user)` or `RemovedBlackList(address _user)`,
and answers `isBlackListed(address) -> bool`. Both were read from the contracts' own
published interfaces (TronGrid `wallet/getcontract`, Etherscan `getabi`) on 14 Oct 2026.

* Tron: TronGrid `/v1/contracts/{USDT}/events`, oldest first, paged by
  `min_block_timestamp` (a page whose events all share one instant is followed by its
  fingerprint), up to a fixed cut-off so a replay is the same list.
* Ethereum: Etherscan `logs/getLogs` by topic, paged by block up to a fixed block.
* The check: `eth_call` of `isBlackListed` (TronGrid's JSON-RPC, Etherscan's proxy).

Every answer goes through the Fetcher, so it is cached and OFFLINE=1 replays it. Keys
(TRONGRID_API_KEY, ETHERSCAN_API_KEY) never reach a cache key or a log.
"""
from __future__ import annotations

import json

from .addresses import b58check_decode, keccak256, tron_hex_to_base58
from .base import ProviderError
from .cache import Fetcher
from .evm import ETHERSCAN, _check as _check_etherscan
from .http import api_key
from .tron import BASE as TRONGRID, USDT as TRON_USDT

ETH_USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
TRON_JSONRPC = f"{TRONGRID}/jsonrpc"
EVENTS = ("AddedBlackList", "RemovedBlackList")
TOPIC = {e: "0x" + keccak256(f"{e}(address)".encode()).hex() for e in EVENTS}
IS_BLACKLISTED = keccak256(b"isBlackListed(address)")[:4].hex()
CONTRACT = {"tron": TRON_USDT, "ethereum": ETH_USDT}
# each contract's page on a block explorer (cited with the snapshot, never fetched)
EXPLORER = {"tron": f"https://tronscan.org/#/token20/{TRON_USDT}",
            "ethereum": f"https://etherscan.io/token/{ETH_USDT}"}


def tron_hex(address: str) -> str:
    """The 20-byte hex of a Tron address (no 41 prefix), as an EVM-style call wants it."""
    return b58check_decode(address)[1:].hex()


def _check_tron(body) -> None:
    if not isinstance(body, dict) or body.get("success") is not True:
        err = body.get("error") if isinstance(body, dict) else str(body)[:200]
        raise ProviderError(f"TronGrid error: {err}")


def _headers() -> dict:
    key = api_key("TRONGRID_API_KEY")
    return {"TRON-PRO-API-KEY": key} if key else {}


def tron_events(fetcher: Fetcher, event: str, until_ms: int, page_size: int = 200,
                max_pages: int = 2_000) -> list[dict]:
    """Every `event` of Tron USDT up to `until_ms` (block time, ms), oldest first."""
    fetcher.min_interval.setdefault("api.trongrid.io", 0.1 if api_key("TRONGRID_API_KEY") else 1.0)
    url = f"{TRONGRID}/v1/contracts/{TRON_USDT}/events"
    seen: set[tuple[str, int]] = set()
    out: list[dict] = []
    cursor, fingerprint = 0, None
    for _ in range(max_pages):
        params = {"event_name": event, "only_confirmed": "true", "limit": page_size,
                  "order_by": "block_timestamp,asc", "min_block_timestamp": cursor,
                  "max_block_timestamp": until_ms}
        if fingerprint:
            params["fingerprint"] = fingerprint
        body = fetcher.get_json("tron", TRON_USDT, event, url, params, headers=_headers(),
                                check=_check_tron)
        rows = body.get("data") or []
        fresh = 0
        for r in rows:
            key = (r["transaction_id"], int(r.get("event_index", 0)))
            if key in seen:
                continue
            seen.add(key)
            fresh += 1
            raw = r["result"].get("_user") or r["result"]["0"]
            out.append({"chain": "tron", "event": event,
                        "address": tron_hex_to_base58("41" + raw.removeprefix("0x")[-40:]),
                        "time_ms": int(r["block_timestamp"]), "block": int(r["block_number"]),
                        "tx": r["transaction_id"], "index": key[1]})
        if len(rows) < page_size:
            break
        last = int(rows[-1]["block_timestamp"])
        if last > cursor and fresh:
            cursor, fingerprint = last, None
        else:                       # a whole page at one instant: go on by fingerprint
            fingerprint = (body.get("meta") or {}).get("fingerprint")
            if not fingerprint:
                raise ProviderError(f"TronGrid gave a full page of {event} at one instant "
                                    "and no way to go on")
    else:
        raise ProviderError(f"more than {max_pages} pages of {event}")
    return sorted(out, key=lambda e: (e["time_ms"], e["block"], e["tx"], e["index"]))


def _hex(v: str) -> int:
    """An explorer's hex number; it writes zero as a bare '0x'."""
    return int(v, 16) if v not in ("0x", "") else 0


def _etherscan(fetcher: Fetcher, direction: str, params: dict, check=_check_etherscan) -> dict:
    fetcher.min_interval.setdefault("api.etherscan.io", 0.35)
    return fetcher.get_json("ethereum", ETH_USDT, direction, ETHERSCAN,
                            {"chainid": 1, **params, "apikey": api_key("ETHERSCAN_API_KEY")},
                            check=check)


def eth_block_at(fetcher: Fetcher, unix_s: int) -> int:
    """The last Ethereum block at or before `unix_s`."""
    body = _etherscan(fetcher, "block", {"module": "block", "action": "getblocknobytime",
                                         "timestamp": unix_s, "closest": "before"})
    r = body["result"]
    return int(r["blockNumber"] if isinstance(r, dict) else r)


def eth_logs(fetcher: Fetcher, event: str, to_block: int, page_size: int = 1000,
             max_pages: int = 1_000) -> list[dict]:
    """Every `event` of Ethereum USDT up to block `to_block`, oldest first."""
    seen: set[tuple[str, int]] = set()
    out: list[dict] = []
    cursor, page = 0, 1
    for _ in range(max_pages):
        body = _etherscan(fetcher, event, {
            "module": "logs", "action": "getLogs", "address": ETH_USDT,
            "topic0": TOPIC[event], "fromBlock": cursor, "toBlock": to_block,
            "page": page, "offset": page_size})
        rows = body.get("result") or []
        if isinstance(rows, str):
            rows = []
        for r in rows:
            key = (r["transactionHash"], _hex(r["logIndex"]))
            if key in seen:
                continue
            seen.add(key)
            out.append({"chain": "ethereum", "event": event,
                        "address": "0x" + r["data"].removeprefix("0x")[-40:].lower(),
                        "time_ms": _hex(r["timeStamp"]) * 1000,
                        "block": _hex(r["blockNumber"]), "tx": r["transactionHash"],
                        "index": key[1]})
        if len(rows) < page_size:
            break
        last = _hex(rows[-1]["blockNumber"])
        if last > cursor:           # on from that block (its rest; the overlap is dropped)
            cursor, page = last, 1
        else:                       # one block fills the page: the next page of it
            page += 1
            if page * page_size > 10_000:
                raise ProviderError(f"more than 10,000 {event} logs in block {last}")
    else:
        raise ProviderError(f"more than {max_pages} pages of {event}")
    return sorted(out, key=lambda e: (e["time_ms"], e["block"], e["tx"], e["index"]))


def _word_true(result: str) -> bool:
    if not isinstance(result, str) or not result.startswith("0x"):
        raise ProviderError(f"unexpected eth_call answer: {str(result)[:100]}")
    return int(result, 16) == 1


def _check_rpc(body) -> None:
    if not isinstance(body, dict) or "result" not in body:
        raise ProviderError(f"JSON-RPC error: {str(body)[:200]}")


def is_blacklisted(fetcher: Fetcher, chain: str, address: str) -> bool:
    """The contract's own answer: is `address` on USDT's blacklist now?"""
    if chain == "tron":
        call = {"to": "0x" + tron_hex(TRON_USDT),
                "data": "0x" + IS_BLACKLISTED + "0" * 24 + tron_hex(address)}
        body = fetcher.get_json("tron", address, "isBlackListed", TRON_JSONRPC,
                                {"method": "eth_call", "params": json.dumps([call, "latest"])},
                                headers=_headers(), check=_check_rpc, rpc=True)
        return _word_true(body["result"])
    if chain == "ethereum":
        body = _etherscan(fetcher, "isBlackListed", {
            "module": "proxy", "action": "eth_call", "to": ETH_USDT, "tag": "latest",
            "data": "0x" + IS_BLACKLISTED + "0" * 24 + address.lower().removeprefix("0x")},
            check=_check_rpc)
        return _word_true(body.get("result"))
    raise ValueError(f"no USDT blacklist read for {chain}")
