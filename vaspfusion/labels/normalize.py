"""Normalisation rules that turn heterogeneous label sources into one schema.

Pure functions only: the builder (load.py) applies them row by row, and every
rule here has a test built from a real row of research/data.

Two judgement calls live here and are worth reading before changing anything:

* TIERS. A label is only as good as whoever published it. An exchange's own
  proof-of-reserves list beats a curated list (OFAC, cex-list, the Dune
  spellbook), which beats a scraped explorer tag, which beats anything we derive
  ourselves. Dedupe keeps the highest tier.
* VASP CATEGORIES. The PS asks for the VASP that took the deposit, and instant
  swap services and custodial wallet providers are VASPs as much as exchanges
  are. The upstream data files them under `entity`, so they would be invisible
  to attribution without the remap below. Token contracts and deployers that
  upstream filed under `exchange` are the opposite case: contracts, not custody
  wallets, so they are demoted to `entity`.
"""
from __future__ import annotations

import re

EVM_CHAINS = frozenset({
    "evm",  # chain-agnostic EVM rows (the Dune spellbook's "EVM")
    "ethereum", "bsc", "polygon", "arbitrum", "optimism", "base", "avalanche",
    "gnosis", "celo", "worldchain", "linea", "zksync", "fantom", "cronos", "kava",
    "kcc", "klaytn", "metis", "core", "sonic", "hyperliquid", "ethereum-classic",
})

CATEGORIES = ("exchange", "custodial_wallet", "swap_service", "sanctioned", "scam",
              "mixer", "bridge", "defi", "entity")
KINDS = ("hot", "cold", "deposit", "reserve", "unknown")
TIER_RANK = {"published_por": 4, "curated": 3, "explorer_tag": 2, "derived": 1}
CATEGORY_RANK = {"sanctioned": 6, "scam": 5, "exchange": 4, "custodial_wallet": 4,
                 "swap_service": 4, "mixer": 4, "bridge": 3, "defi": 2, "entity": 1}
VASP_CATEGORIES = frozenset({"exchange", "custodial_wallet", "swap_service"})

_CHAIN_ALIASES = {"trx": "tron", "btc": "bitcoin", "eth": "ethereum", "evm": "evm",
                  "xrp": "xrp", "sol": "solana"}

# Source -> tier. Merged upstream sources are joined with "+"; the best part wins.
_TIER_OF_SOURCE = (
    ("defillama-cex", "published_por"),     # exchange-published proof-of-reserves
    ("ofac-sdn", "curated"),
    ("cex-list", "curated"),
    ("mew-ethereum-lists", "curated"),
    ("dune-spellbook", "curated"),
    ("post-incident report", "curated"),    # operator's own statement (WazirX)
    ("eth-labels", "explorer_tag"),
    ("etherscan", "explorer_tag"),
)

# Upstream `entity` values that name a tag, not an owner. The owner is then read
# from the label ("ChangeNOW 10" -> ChangeNOW).
_GENERIC_ENTITIES = frozenset({
    "exchange", "bridge", "dex", "defi", "blocked", "token-contract",
    "contract-deployer", "old-contract", "token-sale", "bridged-token",
    "website-down", "airdrop-distributor", "fiat-gateway", "fund",
})

_ALIASES = {
    "bitget": "Bitget", "okx": "OKX", "okex": "OKX", "okx (okex)": "OKX",
    "htx": "HTX", "huobi": "HTX", "htx (huobi)": "HTX", "gate": "Gate.io",
    "gate.io": "Gate.io", "kucoin": "KuCoin", "binance": "Binance",
    "coinbase": "Coinbase", "kraken": "Kraken", "bitfinex": "Bitfinex",
    "deribit": "Deribit", "mexc": "MEXC", "coinex": "CoinEx", "bybit": "Bybit",
    "gemini": "Gemini", "ftx": "FTX", "poloniex": "Poloniex", "bithumb": "Bithumb",
    "upbit": "Upbit", "changenow": "ChangeNOW", "celsius-network": "Celsius",
    "celsius": "Celsius", "bitgo": "BitGo", "blockfi": "BlockFi", "nexo": "Nexo",
}

SWAP_SERVICES = frozenset(s.lower() for s in (
    "FixedFloat", "ChangeNOW", "SideShift", "SimpleSwap", "Changelly", "StealthEX",
    "Exolix", "LetsExchange", "Godex", "SwapZone", "SwapSpace", "Quickex", "Flyp.me",
    "Swapuz", "Evercoin", "ShapeShift",
))
CUSTODIAL_PROVIDERS = frozenset(s.lower() for s in (
    "BitGo", "Fireblocks", "Anchorage Digital", "Copper", "Cobo", "Ceffu", "Paxos",
    "Celsius", "BlockFi", "Revolut", "Uphold", "Wirex", "Xapo",
))

_CONTRACT = re.compile(r"\b(token|deployer|airdrop)\b")


def normalize_chain(raw: str) -> str:
    key = raw.strip().lower()
    return _CHAIN_ALIASES.get(key, key)


def normalize_address(address: str, chain: str) -> str:
    """EVM addresses are case-insensitive (the case is only a checksum), so they
    are lowercased. Base58 (Tron, BTC legacy) is case-sensitive and kept as is."""
    a = address.strip()
    return a.lower() if chain in EVM_CHAINS else a


def tier_for(source: str) -> str:
    best = None
    for part in re.split(r"\s*\+\s*", source.strip().lower()):
        tier = next((t for key, t in _TIER_OF_SOURCE if key in part), None)
        if tier and (best is None or TIER_RANK[tier] > TIER_RANK[best]):
            best = tier
    if best is None:
        raise ValueError(f"no tier mapping for label source {source!r}")
    return best


def _name_from_label(label: str) -> str:
    s = label.split(":")[0].strip()
    s = re.sub(r"\s*\(proof-of-reserves\)$", "", s)
    s = re.sub(r"\s+\d+$", "", s)
    return re.sub(r"\.com$", "", s, flags=re.I).strip()


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def canonical_entity(raw_entity: str, label: str) -> str:
    raw = (raw_entity or "").strip()
    key = raw.lower()
    derived = _name_from_label(label or "")
    if derived.lower() == "null":
        derived = ""
    if not raw or key in _GENERIC_ENTITIES:
        name = derived or raw
        return _ALIASES.get(name.lower(), name)
    if key in _ALIASES:
        return _ALIASES[key]
    if raw == key:  # a lowercase slug such as "cex-io": prefer the label's spelling
        if derived and _alnum(derived) == _alnum(raw):
            return derived
        return " ".join(w.capitalize() for w in re.split(r"[-_ ]+", raw) if w)
    return raw


def map_category(raw_category: str, entity: str, label: str) -> str:
    raw = raw_category.strip().lower()
    is_contract = bool(_CONTRACT.search((label or "").lower()))
    ent = entity.lower()
    if raw in ("exchange", "entity") and not is_contract:
        if ent in SWAP_SERVICES:
            return "swap_service"
        if raw == "entity" and ent in CUSTODIAL_PROVIDERS:
            return "custodial_wallet"
    if raw == "exchange" and is_contract:
        return "entity"
    return raw if raw in CATEGORIES else "entity"


def infer_kind(label: str, source: str) -> str:
    lab = (label or "").lower()
    if "deposit funder" in lab:  # funds deposit addresses with gas: an exchange hot wallet
        return "hot"
    if re.search(r"\bdep(osit)?\b", lab):
        return "deposit"
    if re.search(r"\bcold\b", lab):
        return "cold"
    if re.search(r"\bhot\b", lab):
        return "hot"
    if "defillama-cex" in source.lower() or re.search(r"\breserves?\b", lab):
        return "reserve"
    return "unknown"
