"""Where a bridge deposit came out: the destination chain, the recipient and the
payout transaction.

A bridge takes money in on one chain and pays it out on another. The two halves are
separate transactions with nothing on either chain that points at the other, so the
match comes from the bridge's own public index, asked by the deposit transaction.
Each resolver answers for one bridge family and goes through the cache-first
`Fetcher` like every chain request, so a replay offline gives the same answer.

What a resolver returns is the bridge's statement. The amount that arrived is not
taken from it: the trace reads the payout transaction on the destination chain
itself (trace.py), because what a bridge quotes and what the recipient received can
differ (the recorded Across deposits pay a third party out of the output on arrival).

Resolvers, each checked on real deposits (5 Oct 2026, no key needed):
* Across: `GET app.across.to/api/deposit?originChainId=&depositTxHash=`. HTTP 404
  `DepositNotFoundException` when the transaction holds no Across deposit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from .base import ProviderError, Transfer
from .cache import Fetcher

ACROSS = "https://app.across.to/api/deposit"

# EVM chain id -> the chain as this tool names it (the ones an adapter exists for)
EVM_CHAIN_IDS = {1: "ethereum", 10: "optimism", 56: "bsc", 137: "polygon", 8453: "base",
                 42161: "arbitrum", 43114: "avalanche"}
CHAIN_ID_OF = {name: cid for cid, name in EVM_CHAIN_IDS.items()}
# ids a bridge may name that no adapter here reads: named, so the officer knows where to look
OTHER_CHAIN_IDS = {130: "Unichain", 232: "Lens", 324: "zkSync Era", 480: "World Chain",
                   999: "HyperEVM", 1135: "Lisk", 1868: "Soneium", 9745: "Plasma",
                   34443: "Mode", 57073: "Ink", 59144: "Linea", 81457: "Blast",
                   534352: "Scroll", 7777777: "Zora", 34268394551451: "Solana"}


@dataclass(frozen=True)
class BridgeHop:
    """One deposit matched to its payout, as the bridge's index states it."""
    bridge: str                     # the family: "Across"
    source_chain: str
    source_tx: str
    dest_chain: str | None          # a chain this tool has an adapter for, else None
    dest_name: str                  # how to say it: "base", "Linea", "chain id 2020"
    recipient: str
    payout_tx: str
    paid_at: datetime | None
    deposited_at: datetime | None
    source: str                     # who said so: the host that answered
    token_out: str | None = None    # the token contract the bridge says it paid in


@dataclass(frozen=True)
class Unresolved:
    """The deposit could not be matched. `reason` completes "It was not followed: …"."""
    reason: str


class BridgeResolver(Protocol):
    family: str

    def resolve(self, transfer: Transfer) -> BridgeHop | Unresolved:
        """`transfer` is the deposit: a transfer into one of the bridge's wallets."""


def _time(text: str | None) -> datetime | None:
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def _check_across(body) -> None:
    if not isinstance(body, dict):
        raise ProviderError(f"unexpected body from Across: {str(body)[:200]}")
    if body.get("error"):
        if body["error"] == "DepositNotFoundException":
            return                  # an answer: this transaction holds no Across deposit
        raise ProviderError(f"Across: {body['error']}: {str(body.get('message'))[:200]}")
    deposit = body.get("deposit")
    if not isinstance(deposit, dict):
        raise ProviderError(f"unexpected body from Across: {str(body)[:200]}")
    if deposit.get("status") == "pending":
        # not an answer to keep: the relayer has not paid out yet
        raise ProviderError("Across has not paid this deposit out yet")


class AcrossResolver:
    family = "Across"

    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher
        fetcher.min_interval.setdefault("app.across.to", 0.25)

    def resolve(self, transfer: Transfer) -> BridgeHop | Unresolved:
        origin = CHAIN_ID_OF.get(transfer.chain)
        if origin is None:
            return Unresolved(f"Across is not asked about deposits on {transfer.chain}")
        try:
            body = self.fetcher.get_json(
                transfer.chain, transfer.tx_hash, "bridge", ACROSS,
                {"originChainId": origin, "depositTxHash": transfer.tx_hash},
                check=_check_across, accept=(404,))
        except ProviderError as e:
            return Unresolved(f"Across' index could not be read ({e})")
        if body.get("error"):
            return Unresolved("Across' index holds no deposit for this transaction")
        if (body.get("pagination") or {}).get("maxIndex", 0) > 0:
            return Unresolved("the transaction holds several Across deposits, which are not "
                              "told apart")
        d = body["deposit"]
        if d.get("status") != "filled" or not d.get("fillTx"):
            return Unresolved(f"Across reports the deposit as {d.get('status')!r}, not paid "
                              "out on another chain")
        dest_id = int(d["destinationChainId"])
        dest = EVM_CHAIN_IDS.get(dest_id)
        recipient = str(d["recipient"])
        return BridgeHop(
            bridge=self.family, source_chain=transfer.chain, source_tx=transfer.tx_hash,
            dest_chain=dest,
            dest_name=dest or OTHER_CHAIN_IDS.get(dest_id, f"chain id {dest_id}"),
            recipient=recipient.lower() if dest else recipient,
            payout_tx=str(d["fillTx"]).lower(), paid_at=_time(d.get("fillBlockTimestamp")),
            deposited_at=_time(d.get("depositBlockTimestamp")), source="app.across.to",
            token_out=(str(d["outputToken"]).lower() if d.get("outputToken") else None))


# the label store's name for a bridge family -> its resolver
RESOLVERS: dict[str, Callable[[Fetcher], BridgeResolver]] = {
    "Across Protocol": AcrossResolver,
}


class Crossings:
    """What a trace needs to follow money over a bridge: the resolver of a bridge
    label, and the adapter of the chain the money came out on."""

    def __init__(self, fetcher: Fetcher, provider_for: Callable[[str], object]):
        self.fetcher, self.provider_for = fetcher, provider_for
        self._resolvers: dict[str, BridgeResolver] = {}
        self._providers: dict[str, object] = {}
        self._answers: dict[tuple[str, str, str], BridgeHop | Unresolved] = {}

    def resolve(self, entity: str, transfer: Transfer) -> BridgeHop | Unresolved:
        make = RESOLVERS.get(entity)
        if make is None:
            return Unresolved(f"deposits into {entity} cannot be matched to a payout by "
                              "this tool")
        key = (entity, transfer.chain, transfer.tx_hash)
        if key not in self._answers:
            if entity not in self._resolvers:
                self._resolvers[entity] = make(self.fetcher)
            self._answers[key] = self._resolvers[entity].resolve(transfer)
        return self._answers[key]

    def provider(self, chain: str):
        """The destination chain's adapter (raises ProviderError when there is none, or
        none that answers without a key that is not set)."""
        if chain not in self._providers:
            self._providers[chain] = self.provider_for(chain)
        return self._providers[chain]
