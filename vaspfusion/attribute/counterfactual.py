"""Counterfactual check: does a named exchange survive losing its strongest evidence?

The strongest single item behind "this wallet's money reached exchange X" is the
label on the address where it entered X. So that label is hidden and the wallet is
traced and attributed again, with the same settings:

* holds:  X still clears the bar (usually one hop further, at X's own wallet);
* weaker: X is still reached, but below the bar that names an exchange;
* gone:   X is not reached at all, so the answer rests on that one label;
* not checked: the second trace could not look as far as the first (a listing failed,
  the hop limit or the budget was reached behind the hidden label). Nothing is claimed.

It is run for the candidates that were named (outbound, at or above the bar). The
second trace reads through the same cache-first fetcher, so its pages are recorded
and replayed like every other page. The idea of re-scoring without the top evidence
item is from Lokesh-1511's SIH entry (research/COMPETITOR_SCAN.md).
"""
from __future__ import annotations

from dataclasses import replace

from ..chains.base import ProviderError
from ..explain import fmt
from ..trace import TraceConfig, TraceResult, trace
from ..trace import ZERO
from .rules import UNROUTABLE, Attribution, Candidate, RuleConfig, attribute

MAX_CHECKED = 3
# why traced money stopped without the trace having seen where it went
_BLIND = {"error": "a listing could not be read", "depth_limit": "the hop limit was reached",
          "budget": "the trace budget was spent", "truncated": "a listing was cut short",
          "small": "the parts became too small to follow",
          "pooled": "the money was pooled with other wallets' coins in one transaction",
          "coinjoin": "the money entered a CoinJoin-shaped transaction"}


def _blind_spots(first: TraceResult, second: TraceResult) -> list[str]:
    """Reasons the second trace left more money unseen than the first did."""
    return [words for reason, words in _BLIND.items()
            if second.stopped.get(reason, ZERO) > first.stopped.get(reason, ZERO)]


class HiddenLabels:
    """A label lookup that does not know the given addresses."""

    def __init__(self, labels, hidden: set[str]):
        self.labels, self.hidden = labels, set(hidden)

    def lookup_many(self, pairs):
        return {k: v for k, v in self.labels.lookup_many(pairs).items()
                if k[0] not in self.hidden}

    def infer(self, address: str, chain: str):
        """A label derived from the wallet's cluster (Bitcoin) is hidden like any other;
        every other wallet keeps its own."""
        inner = getattr(self.labels, "infer", None)
        return None if inner is None or address in self.hidden else inner(address, chain)


def _verdict(c: Candidate, again: Candidate | None, rules: RuleConfig) -> tuple[bool, str]:
    without = f"the label on {fmt.short(c.deposit_address)}"
    if again is None:
        return False, (f"Without {without}, {c.vasp} is not reached at all: naming {c.vasp} "
                       "rests on that one label.")
    where = (f"{fmt.pct(again.share)} of the funds reach {c.vasp} at "
             f"{fmt.short(again.deposit_address)} ({fmt.tier_words(again.label.tier)}) in "
             f"{fmt.hops(again.hops_min, again.hops_max)}")
    if again.confidence >= rules.attribute_min:
        return True, (f"Still {c.vasp} without {without}: {where}, confidence "
                      f"{again.confidence:.2f} (was {c.confidence:.2f}).")
    return False, (f"Without {without}, {where}, but confidence falls to "
                   f"{again.confidence:.2f}, below the {rules.attribute_min:.2f} needed to name "
                   f"an exchange (was {c.confidence:.2f}).")


def check(c: Candidate, tr: TraceResult, provider, labels, cfg: TraceConfig,
          rules: RuleConfig) -> Candidate:
    """`c` with its counterfactual filled in; unchanged if the second trace cannot run."""
    try:
        tr2 = trace(tr.address, tr.chain, provider, HiddenLabels(labels, {c.deposit_address}),
                    cfg)
    except ProviderError:
        return c
    again = next((x for x in attribute(tr2, rules).candidates
                  if x.direction == "outbound" and x.vasp == c.vasp and x.hops > 0), None)
    blind = _blind_spots(tr, tr2) if again is None else []
    if blind:
        # "not reached" would be a guess: the money behind the hidden label was not followed
        text = (f"Not checked: without the label on {fmt.short(c.deposit_address)} the trace "
                f"could not follow the money further ({'; '.join(blind)}).")
        return replace(c, counterfactual=text, counterfactual_holds=None)
    holds, text = _verdict(c, again, rules)
    item = {"kind": "counterfactual", "tier": None, "text": text,
            "tx_hashes": [e.transfer.tx_hash for e in again.path_edges] if again else [],
            "weight": round((again.confidence if again else 0.0) - c.confidence, 4)}
    return replace(c, counterfactual=text, counterfactual_holds=holds,
                   evidence=[*c.evidence, item])


def add_counterfactuals(tr: TraceResult, att: Attribution, provider, labels,
                        cfg: TraceConfig = TraceConfig(),
                        rules: RuleConfig = RuleConfig()) -> None:
    """Fill in the counterfactual of every named candidate (at most MAX_CHECKED, nearest
    first). Nothing else about the attribution changes."""
    # a wallet tagged "exchange" with no owner has no exchange to be "still" reached
    named = [c for c in att.candidates if c.direction == "outbound" and c.hops > 0
             and c.vasp != UNROUTABLE and c.confidence >= rules.attribute_min][:MAX_CHECKED]
    done = {id(c): check(c, tr, provider, labels, cfg, rules) for c in named}
    if att.top is not None:
        att.top = done.get(id(att.top), att.top)
    att.candidates = [done.get(id(c), c) for c in att.candidates]
