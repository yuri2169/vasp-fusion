"""How numbers, addresses and durations are written in everything an officer reads."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

TIER_WORDS = {
    "published_por": "published by the exchange itself",
    "curated": "curated list",
    "explorer_tag": "explorer tag",
    "derived": "derived by VASP-FUSION",
}


CHAIN_NAMES = {"tron": "Tron", "ethereum": "Ethereum", "bsc": "BNB Smart Chain",
               "polygon": "Polygon", "arbitrum": "Arbitrum", "base": "Base",
               "optimism": "Optimism", "avalanche": "Avalanche", "bitcoin": "Bitcoin",
               "solana": "Solana"}


def chain_name(chain: str) -> str:
    return CHAIN_NAMES.get(chain, chain.title())


def short(address: str) -> str:
    """TVZpWt…KjUtzR. Short names (and anything under 16 characters) are kept whole. A
    wallet the money reached on another chain (id `chain:address`, chains/base.py) is
    written with its chain: 0x2102…f364b0 on Base."""
    chain, sep, plain = address.partition(":")
    if sep:
        return f"{short(plain)} on {chain_name(chain)}"
    return address if len(address) <= 16 else f"{address[:6]}…{address[-6:]}"


def amount(value, asset: str | None = None) -> str:
    """48,500 USDT · 252,163.80 USDT · 0.002428 ETH. Whole sums have no decimals, other
    sums of 1 or more have two, and smaller ones up to six."""
    d = Decimal(value)
    if abs(d) >= 1:
        q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        text = f"{q:,.0f}" if q == q.to_integral_value() else f"{q:,.2f}"
    else:
        text = f"{d.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP):f}"
        text = text.rstrip("0").rstrip(".") if "." in text else text
    return f"{text} {asset}" if asset else text


def pct(share) -> str:
    """Whole percent. Never rounds a part up to 100% or down to 0%."""
    s = float(share)
    if s <= 0:
        return "0%"
    if s >= 1:
        return "100%"
    whole = round(s * 100)
    if whole >= 100:
        return "99%"
    if whole < 1:
        return "under 1%"
    return f"{whole}%"


def prob(p) -> str:
    """A probability to two decimals, never written as certain: 0.97, over 0.99, under 0.01."""
    p = float(p)
    if p > 0.995:
        return "over 0.99"
    if p < 0.005:
        return "under 0.01"
    return f"{p:.2f}"


def prob_range(low, high) -> str:
    """"range 0.89 to 0.99", or that it is too narrow to show at two decimals."""
    low, high = float(low), float(high)
    if high - low < 0.01:
        return "range narrower than 0.01"
    return f"range {prob(low)} to {prob(high)}"


def duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "an unknown time"
    s = int(seconds)
    if s < 60:
        return f"{s} second{'s' if s != 1 else ''}"
    for size, name in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if s >= size:
            n = round(s / size)
            return f"{n} {name}{'s' if n != 1 else ''}"
    return f"{s} seconds"


def hops(n: int, upto: int | None = None) -> str:
    """"2 hops", or "2 to 3 hops" when the money took routes of different lengths."""
    if upto is not None and upto != n:
        return f"{n} to {upto} hops"
    return f"{n} hop{'s' if n != 1 else ''}"


def tier_words(tier: str) -> str:
    return TIER_WORDS.get(tier, tier)
