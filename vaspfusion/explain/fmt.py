"""How numbers, addresses and durations are written in everything an officer reads."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

TIER_WORDS = {
    "published_por": "published by the exchange itself",
    "curated": "curated list",
    "explorer_tag": "explorer tag",
    "derived": "derived by VASP-FUSION",
}


def short(address: str) -> str:
    """TVZpWt…KjUtzR. Short names (and anything under 16 characters) are kept whole."""
    return address if len(address) <= 16 else f"{address[:6]}…{address[-6:]}"


def amount(value, asset: str | None = None) -> str:
    """48,500 USDT · 252,163.80 USDT · 0.0024 ETH. Two decimals for sums of 1 or more,
    up to six significant decimals below that; trailing zeros dropped."""
    d = Decimal(value)
    q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if abs(d) >= 1 \
        else d.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    text = f"{q:,f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
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


def hops(n: int) -> str:
    return f"{n} hop{'s' if n != 1 else ''}"


def tier_words(tier: str) -> str:
    return TIER_WORDS.get(tier, tier)
