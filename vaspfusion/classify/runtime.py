"""The deposit-address model at runtime: read one wallet the way the training set was
read, and say how likely it behaves like an exchange deposit address.

Used on the unlabelled wallets a trace stops at (attribute/leads.py). The reading
protocol is B6's (classify/dataset.py): the wallet's earliest `limit` stablecoin
transfers since `lookback_days` before the traced money arrived, its gas listing over
the same span, only the first `horizon_days` from its first real transfer, and the
listing of the wallet it pays most, read the same way. The model reads behaviour
only, so no label is looked up here.

Only chains in `SCORED_CHAINS` are scored. Tron's model recognised the deposit
addresses of an exchange it had never seen (leave-one-exchange-out, B6); Ethereum's
did not (pooled recall 0.10), and "an exchange we hold no label for" is exactly the
unseen-exchange case.

What a score is not: the model was measured on exchange customers and deposit
addresses. A wallet that never dealt with an exchange is outside what was measured,
so a high score is a lead to check, not a finding.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

from ..chains import get_provider
from ..discover.crawl import _stable_rows
from ..discover.rules import DiscoverConfig
from .dataset import _window
from .explain import reasons
from .features import FEATURES, address_features, top_recipient
from .train import VERSION, Fitted, load_model, predict

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "artifacts" / VERSION
SCORED_CHAINS = ("tron",)


@dataclass(frozen=True)
class Score:
    address: str
    p: float
    low: float
    high: float
    reasons: list[dict]
    collector: str | None          # the wallet it pays most (what a deposit address sweeps into)
    features: dict
    n_rows: int
    complete: bool


class Scorer:
    def __init__(self, model: Fitted, provider, rules: DiscoverConfig = DiscoverConfig(),
                 limit: int = 50, lookback_days: float = 7.0, horizon_days: float = 14.0):
        self.model, self.provider, self.rules = model, provider, rules
        self.limit = limit
        self.lookback = timedelta(days=lookback_days)
        self.horizon = timedelta(days=horizon_days)

    def score(self, address: str, arrived_at: datetime) -> Score | None:
        """None when the wallet has no usable stablecoin transfer in the window. Raises
        ProviderError when a listing cannot be read."""
        since = arrived_at - self.lookback
        rows, complete = _stable_rows(self.provider, address, "both", since, self.limit)
        events = self.provider.gas_events(address, since=since)
        rows, events = _window(address, rows, events, None, self.horizon, self.rules)
        collector = top_recipient(address, rows, self.rules.dust)
        theirs = None
        if collector is not None:
            theirs = _stable_rows(self.provider, collector, "both", since, self.limit)[0]
        f = address_features(address, rows, events, None, cfg=self.rules, recipient_rows=theirs)
        if f is None:
            return None
        df = pl.DataFrame([{k: f[k] for k in FEATURES}],
                          schema={k: pl.Float64 for k in FEATURES})
        pred = predict(self.model, df)
        return Score(address=address, p=round(float(pred["p"][0]), 4),
                     low=round(float(pred["low"][0]), 4), high=round(float(pred["high"][0]), 4),
                     reasons=reasons(self.model, df, top=3)[0], collector=collector,
                     features={k: f[k] for k in FEATURES}, n_rows=f["n_rows"],
                     complete=bool(complete))


def make_scorer(chain: str, fetcher, model_dir: Path | str = MODEL_DIR, **opts) -> Scorer | None:
    """The scorer for `chain`, or None when the chain is not scored or its model is not
    on disk (`make model` writes it)."""
    if chain not in SCORED_CHAINS:
        return None
    try:
        model = load_model(Path(model_dir) / chain)
    except FileNotFoundError:
        return None
    # the training set's protocol: one page of 50 rows per listing
    return Scorer(model, get_provider(chain, fetcher, page_size=50, max_pages=1, **opts))
