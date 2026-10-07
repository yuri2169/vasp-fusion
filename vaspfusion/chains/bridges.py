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

Resolvers, each checked on real deposits (no key needed):
* Across (5 Oct 2026): `GET app.across.to/api/deposit?originChainId=&depositTxHash=`.
  HTTP 404 `DepositNotFoundException` when the transaction holds no Across deposit.
* Stargate over LayerZero (8 Oct 2026): `GET scan.layerzero-api.com/v1/messages/tx/<hash>`.
  HTTP 404 when the transaction sent no LayerZero message. The index names the two
  chains and the delivery transaction; the recipient is read from the message itself
  (a Stargate transfer states it), and is then checked like any other: the payout must
  be among that address's transfers on the destination chain, or nothing is followed.
* Wormhole's token bridge (8 Oct 2026): `GET api.wormholescan.io/api/v1/operations?txHash=`.
  An empty list when the transaction holds no Wormhole transfer. The token bridge pays
  out its own wrapped token and only when someone redeems the transfer, so many
  deposits are matched and named, not followed.
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
    bridge: str                     # the family: "Across", "Stargate", "Wormhole"
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


LAYERZERO = "https://scan.layerzero-api.com/v1/messages/tx"
# LayerZero endpoint id -> the chain as this tool names it (the ones an adapter exists for)
LAYERZERO_EIDS = {30101: "ethereum", 30102: "bsc", 30106: "avalanche", 30109: "polygon",
                  30110: "arbitrum", 30111: "optimism", 30184: "base"}
_LZ_WAITING = ("INFLIGHT", "CONFIRMING", "PAYLOAD_STORED")
_STARGATE_TAXI = 1                  # the first byte of a Stargate message that pays one recipient


def _unix(value) -> datetime | None:
    return datetime.fromtimestamp(int(value), timezone.utc) if value else None


def _check_layerzero(body) -> None:
    if not isinstance(body, dict):
        raise ProviderError(f"unexpected body from LayerZero Scan: {str(body)[:200]}")
    if body.get("code") == 4040:
        return                      # an answer: the transaction sent no LayerZero message
    rows = body.get("data")
    if not isinstance(rows, list):
        raise ProviderError(f"unexpected body from LayerZero Scan: {str(body)[:200]}")
    if any(((m.get("status") or {}).get("name")) in _LZ_WAITING for m in rows):
        # not an answer to keep: the message is still on its way
        raise ProviderError("the LayerZero message has not been delivered yet")


def stargate_recipient(payload: str | None) -> str | None:
    """The recipient a Stargate message names, or None when the message is not a Stargate
    transfer to one recipient: message type (1 byte, 1), asset id (2), recipient (32, an
    address left-padded with zeros), amount (8)."""
    raw = (payload or "").removeprefix("0x")
    if len(raw) < 86 or int(raw[:2], 16) != _STARGATE_TAXI or set(raw[6:30]) != {"0"}:
        return None
    return "0x" + raw[30:70].lower()


class LayerZeroResolver:
    """Stargate deposits, matched through LayerZero Scan."""
    family = "Stargate"

    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher
        fetcher.min_interval.setdefault("scan.layerzero-api.com", 0.25)

    def resolve(self, transfer: Transfer) -> BridgeHop | Unresolved:
        try:
            body = self.fetcher.get_json(
                transfer.chain, transfer.tx_hash, "bridge", f"{LAYERZERO}/{transfer.tx_hash}",
                {}, check=_check_layerzero, accept=(404,))
        except ProviderError as e:
            return Unresolved(f"LayerZero Scan could not be read ({e})")
        rows = body.get("data") or []
        if not rows:
            return Unresolved("LayerZero Scan holds no message for this transaction (a "
                              "Stargate deposit that waits for a shared delivery sends its "
                              "message in a later transaction)")
        if len(rows) > 1:
            return Unresolved("the transaction sent several LayerZero messages, which are "
                              "not told apart")
        m = rows[0]
        status = (m.get("status") or {}).get("name")
        dest_tx = ((m.get("destination") or {}).get("tx") or {})
        if status != "DELIVERED" or not dest_tx.get("txHash"):
            return Unresolved(f"LayerZero Scan reports the message as {status!r}, not "
                              "delivered on another chain")
        source_tx = ((m.get("source") or {}).get("tx") or {})
        recipient = stargate_recipient(source_tx.get("payload"))
        if recipient is None:
            return Unresolved("the LayerZero message is not a Stargate transfer to one "
                              "recipient, so it does not say who was paid")
        pathway = m.get("pathway") or {}
        eid = int(pathway.get("dstEid") or 0)
        dest = LAYERZERO_EIDS.get(eid)
        named = (pathway.get("receiver") or {}).get("chain")
        return BridgeHop(
            bridge=self.family, source_chain=transfer.chain, source_tx=transfer.tx_hash,
            dest_chain=dest, dest_name=dest or named or f"LayerZero endpoint {eid}",
            recipient=recipient, payout_tx=str(dest_tx["txHash"]).lower(),
            paid_at=_unix(dest_tx.get("blockTimestamp")),
            deposited_at=_unix(source_tx.get("blockTimestamp")),
            source="scan.layerzero-api.com")


WORMHOLE = "https://api.wormholescan.io/api/v1/operations"
# Wormhole chain id -> the chain as this tool names it (the ones an adapter exists for)
WORMHOLE_CHAINS = {1: "solana", 2: "ethereum", 4: "bsc", 5: "polygon", 6: "avalanche",
                   23: "arbitrum", 24: "optimism", 30: "base"}
OTHER_WORMHOLE_CHAINS = {3: "Terra", 8: "Algorand", 10: "Fantom", 13: "Kaia (Klaytn)",
                         14: "Celo", 15: "NEAR", 16: "Moonbeam", 19: "Injective", 21: "Sui",
                         22: "Aptos", 32: "Sei", 34: "Scroll", 35: "Mantle"}


def _check_wormhole(body) -> None:
    if not isinstance(body, dict) or not isinstance(body.get("operations"), list):
        raise ProviderError(f"unexpected body from Wormholescan: {str(body)[:200]}")
    for op in body["operations"]:
        target = op.get("targetChain") or {}
        if target.get("status") != "completed" or not (target.get("transaction") or {}).get(
                "txHash"):
            # not an answer to keep: nobody has redeemed the transfer on the other chain yet
            raise ProviderError("the transfer has not been paid out on the destination "
                                "chain yet")


class WormholeResolver:
    """Deposits into Wormhole's token bridge, matched through Wormholescan."""
    family = "Wormhole"

    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher
        fetcher.min_interval.setdefault("api.wormholescan.io", 0.25)

    def resolve(self, transfer: Transfer) -> BridgeHop | Unresolved:
        try:
            body = self.fetcher.get_json(
                transfer.chain, transfer.tx_hash, "bridge", WORMHOLE,
                {"txHash": transfer.tx_hash}, check=_check_wormhole)
        except ProviderError as e:
            return Unresolved(f"Wormholescan could not be read ({e})")
        ops = body["operations"]
        if not ops:
            return Unresolved("Wormholescan holds no transfer for this transaction")
        if len(ops) > 1:
            return Unresolved("the transaction holds several Wormhole transfers, which are "
                              "not told apart")
        op = ops[0]
        said = (op.get("content") or {}).get("standarizedProperties") or {}
        target, source = op["targetChain"], op.get("sourceChain") or {}
        if not said.get("toAddress") or not said.get("toChain"):
            return Unresolved("Wormholescan does not say who the transfer was paid to")
        chain_id = int(said["toChain"])
        dest = WORMHOLE_CHAINS.get(chain_id)
        recipient = str(said["toAddress"])
        evm = dest is not None and dest != "solana"
        return BridgeHop(
            bridge=self.family, source_chain=transfer.chain, source_tx=transfer.tx_hash,
            dest_chain=dest,
            dest_name=dest or OTHER_WORMHOLE_CHAINS.get(chain_id, f"Wormhole chain {chain_id}"),
            recipient=recipient.lower() if evm or recipient.startswith("0x") else recipient,
            payout_tx=str(target["transaction"]["txHash"]).lower() if evm
            or str(target["transaction"]["txHash"]).startswith("0x")
            else str(target["transaction"]["txHash"]),
            paid_at=_time(target.get("timestamp")), deposited_at=_time(source.get("timestamp")),
            source="api.wormholescan.io")


# the label store's name for a bridge family -> its resolver
RESOLVERS: dict[str, Callable[[Fetcher], BridgeResolver]] = {
    "Across Protocol": AcrossResolver,
    "Stargate": LayerZeroResolver,
    "Stargate Finance": LayerZeroResolver,
    "Wormhole": WormholeResolver,
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
