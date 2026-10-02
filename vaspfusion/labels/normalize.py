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
DERIVED_SOURCE = "vaspfusion-discover"     # the `source` of every tier=derived row (B4)
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
    # GraphSense TagPacks (B5). The exchange-wallets packs each cite the exchange's own
    # publication. Every other pack is an outside observation (WalletExplorer's own
    # clustering, a news report), like an explorer's tag.
    ("graphsense-tagpack:exchange-wallets-", "curated"),
    ("graphsense-tagpack:", "explorer_tag"),
)

# TagPack `actor` slugs -> the name the rest of the store uses for that owner.
_TAGPACK_ACTORS = {
    "bitmex": "BitMEX", "cryptocom": "Crypto.com", "swissborg": "SwissBorg",
    "bitstamp": "Bitstamp", "hitbtc": "HitBTC", "korbit": "Korbit", "luno": "Luno",
    "bittrex": "Bittrex", "okcoin": "Okcoin", "paxful": "Paxful", "bitso": "Bitso",
    "cex": "CEX.IO", "yobit": "Yobit", "exmo": "Exmo", "btce": "BTC-e",
    "coinspot": "CoinSpot", "coinhako": "Coinhako", "maicoin": "MaiCoin",
    "mercadobitcoin": "Mercado Bitcoin", "bitpanda": "Bitpanda",
    "bitzlato": "Bitzlato", "blocktrades": "BlockTrades Exchange", "btcmarkets": "BTC Markets",
    "litebit": "LiteBit", "quadrigacx": "QuadrigaCX",
}

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
    "upbit": "Upbit", "uphold.com": "Uphold", "changenow": "ChangeNOW", "celsius-network": "Celsius",
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

# Canonical spelling for every name the rules above know about.
_CANONICAL = {**{s.lower(): s for s in (
    "FixedFloat", "ChangeNOW", "SideShift", "SimpleSwap", "Changelly", "StealthEX",
    "Exolix", "LetsExchange", "Godex", "SwapZone", "SwapSpace", "Quickex", "Flyp.me",
    "Swapuz", "Evercoin", "ShapeShift", "BitGo", "Fireblocks", "Anchorage Digital",
    "Copper", "Cobo", "Ceffu", "Paxos", "Celsius", "BlockFi", "Revolut", "Uphold",
    "Wirex", "Xapo")}, **_ALIASES}

_CONTRACT = re.compile(r"\b(token|deployer|airdrop)\b")


def normalize_chain(raw: str) -> str:
    key = raw.strip().lower()
    return _CHAIN_ALIASES.get(key, key)


def normalize_address(address: str, chain: str) -> str:
    """EVM addresses are case-insensitive (the case is only a checksum), so they
    are lowercased. Base58 (Tron, BTC legacy) is case-sensitive and kept as is."""
    a = address.strip()
    return a.lower() if chain in EVM_CHAINS else a


_VALIDATED = ("tron", "bitcoin", "ethereum", "solana")


def address_chain(address: str, chain: str) -> str | None:
    """The chain a label's address really belongs to, or None if it is unusable.

    Only Tron, Bitcoin, EVM and Solana have validators (vaspfusion.chains); rows
    on other chains are kept as filed. An address that fails its filed chain but
    is valid on another is re-filed there (the 0xB10C OFAC list files a Tron
    address as XBT); one valid nowhere (upstream truncated some Base addresses to
    '0x1985EA6E...2Fdb25c87') can never match and is dropped."""
    from vaspfusion.chains.addresses import detect_chain, validate
    from vaspfusion.chains.base import InvalidAddress

    family = "ethereum" if chain in EVM_CHAINS else chain
    if family not in _VALIDATED or validate(address, family):
        return chain
    try:
        return detect_chain(address)
    except InvalidAddress:
        return None


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
    s = re.sub(r"\s+Dep$", "", s)  # "OKX Dep: 0x46C..." is an OKX deposit address
    return s.strip()


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def canonical_entity(raw_entity: str, label: str) -> str:
    raw = (raw_entity or "").strip()
    key = raw.lower()
    derived = _name_from_label(label or "")
    if derived.lower() == "null":
        derived = ""
    if not raw or key in _GENERIC_ENTITIES:
        if not derived or derived.lower() == key:
            # The label is only the tag ("exchange"): some exchange, nobody knows
            # which. Still a VASP hit, but not one a request can be addressed to.
            return f"Unidentified {raw}".strip()
        return _CANONICAL.get(derived.lower(), derived)
    if key in _CANONICAL:
        return _CANONICAL[key]
    if raw == key:  # a lowercase slug such as "cex-io": prefer the label's spelling
        if derived and _alnum(derived) == _alnum(raw):
            return derived
        return " ".join(w.capitalize() for w in re.split(r"[-_ ]+", raw) if w)
    return raw


def tagpack_entity(actor: str, label: str) -> str:
    """The owner of a TagPack tag. A known `actor` gets the store's spelling (huobi ->
    HTX). Otherwise WalletExplorer's own name for the site is kept whole
    ("QuadrigaCX.com"), and a pack with a descriptive label ("swisborg reserve
    wallets") falls back to the actor slug."""
    key = (actor or "").strip().lower()
    if key in _TAGPACK_ACTORS:
        return _TAGPACK_ACTORS[key]
    if key in _CANONICAL:
        return _CANONICAL[key]
    label = (label or "").strip()
    if label and " " not in label:
        return label
    return " ".join(w.capitalize() for w in re.split(r"[-_ ]+", key) if w) or label


def map_category(raw_category: str, entity: str, label: str, raw_entity: str = "") -> str:
    raw = raw_category.strip().lower()
    # Etherscan's generic "Exchange" tag, filed upstream as `entity`: the owner was
    # read from the label, and the tag says it is an exchange. Only this per-row
    # signal promotes; an owner name alone does not, because some upstream slugs
    # contradict their own labels (5,000 "Binance Dep" rows under `bilaxy`).
    if raw == "entity" and raw_entity.strip().lower() == "exchange":
        raw = "exchange"
    is_contract = bool(_CONTRACT.search((label or "").lower()))
    ent = entity.lower()
    if raw in ("exchange", "entity") and not is_contract:
        if ent in SWAP_SERVICES:
            return "swap_service"
        # Upstream `exchange` rows stay exchanges (Nexo); only untyped rows move.
        if raw_category.strip().lower() == "entity" and ent in CUSTODIAL_PROVIDERS:
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
