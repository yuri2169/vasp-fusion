"""Rupees beside US dollar amounts, at one dated reference rate (config/fx.yaml).

The rate is read from the file and never estimated. Everything that shows a rupee amount
also shows `basis()`: which rate, whose, and of what date.
"""
from __future__ import annotations

import os
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "config" / "fx.yaml"


class FxError(ValueError):
    """config/fx.yaml breaks its own rule (a rate without a date or a source)."""


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    doc = (yaml.safe_load(Path(path).read_text()) or {}).get("usd_inr") or {}
    rate, as_of, source = doc.get("rate"), doc.get("as_of"), doc.get("source") or {}
    if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
        raise FxError("usd_inr.rate must be a positive number")
    if not isinstance(as_of, date):
        raise FxError("usd_inr.as_of must be the date the rate is for")
    if not doc.get("name") or not source.get("url") or not source.get("title"):
        raise FxError("usd_inr needs a name and a source with a title and a url")
    return {"rate": float(rate), "as_of": as_of, "name": str(doc["name"]),
            "source_title": str(source["title"]), "source_publisher": source.get("publisher"),
            "source_url": str(source["url"]), "published": source.get("published"),
            "accessed": source.get("accessed")}


def usd_inr(path: Path | str | None = None) -> dict:
    """The rate as the API returns it (`FxRate`)."""
    return dict(_load(str(path or os.environ.get("VASPFUSION_FX") or DEFAULT_PATH)))


def group_indian(whole: int) -> str:
    """12,34,567: the last three digits, then twos."""
    sign, digits = ("-" if whole < 0 else ""), str(abs(whole))
    if len(digits) <= 3:
        return sign + digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    return sign + ",".join([head, *parts, tail])


# The PDFs are set in a face that has no rupee sign: they write "Rs", as the case file
# already does for the amount a complaint reports.
PRINT = "Rs "
# Amounts in these assets are US dollars one for one (as desk/routing.py counts them).
USD_ASSETS = frozenset({"USDT", "USDC"})


def inr(usd, fx: dict | None = None, sign: str = "₹") -> str:
    """A US dollar amount in rupees at the reference rate: ₹1,46,559. No paise."""
    fx = fx or usd_inr()
    rupees = (Decimal(str(usd)) * Decimal(str(fx["rate"]))).quantize(Decimal("1"), ROUND_HALF_UP)
    return f"{sign}{group_indian(int(rupees))}"


def beside(amount, asset: str | None, sign: str = PRINT, fx: dict | None = None) -> str:
    """What goes after an amount in a dollar asset: " (Rs 1,46,559)". Nothing otherwise."""
    if amount is None or (asset or "").upper() not in USD_ASSETS:
        return ""
    return f" ({inr(amount, fx, sign)})"


def basis(fx: dict | None = None, sign: str = "₹") -> str:
    """₹ at 1 USD = ₹95.79, RBI reference rate, 18 Sep 2026"""
    fx = fx or usd_inr()
    d = fx["as_of"]
    return f"{sign} at 1 USD = {sign}{fx['rate']:.2f}, {fx['name']}, {d.day} {d:%b %Y}".replace("  ", " ")
