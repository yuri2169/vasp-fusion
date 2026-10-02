"""What a running trace is doing, in one sentence for the officer who is watching it.

The figures come from the trace itself (`trace(..., on_progress=)`): nothing here is an
estimate, and there is no percentage, because a trace does not know how much is left.
"""
from __future__ import annotations

from .case_narrative import CHAIN_NAMES

# Owners an officer reads as a place to write to are named plainly; anything else says what it is.
_PLAIN = {"exchange", "custodial_wallet", "swap_service"}


def _n(count: int, word: str) -> str:
    return f"{count:,} {word}{'' if count == 1 else 's'}"


def _read(p: dict) -> str:
    asset = f"{p['asset']} " if p.get("asset") else ""
    return (f"{p['transfers_read']:,} {asset}transfer{'' if p['transfers_read'] == 1 else 's'} "
            f"of {_n(p['wallets_read'], 'wallet')}")


def _reached(p: dict, lead: str) -> str:
    names = [r["entity"] if r["category"] in _PLAIN else f"{r['entity']} ({r['category']})"
             for r in p.get("reached") or []]
    return f" {lead}: {', '.join(names)}." if names else ""


def progress_sentence(chain: str, progress: dict) -> str:
    """`progress` is a snapshot from the trace (or the "reading" one a run starts with)."""
    where = CHAIN_NAMES.get(chain, chain.title())
    phase = progress["phase"]
    if phase == "reading":
        return f"Reading the wallet's transfers on {where}."
    if phase == "outbound":
        return (f"Following the money on {where}: {_read(progress)} read, "
                f"{_n(progress['hop'], 'hop')} out." + _reached(progress, "Reached so far"))
    if phase == "inbound":
        return (f"Followed the money {_n(progress['hop'], 'hop')} out on {where} "
                f"({_read(progress)}). Now reading who funded the wallet."
                + _reached(progress, "Reached so far"))
    # checking: attribution, the counterfactual traces, the deposit-address model
    if not progress["transfers_read"]:
        return f"Read the wallet's transfers on {where}. Now checking the result."
    return (f"Read {_read(progress)} on {where}. Now checking the result: each exchange that "
            "would be named is traced again without its label." + _reached(progress, "Reached"))
