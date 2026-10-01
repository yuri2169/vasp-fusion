"""Toy building blocks for the trace / rule tests.

The wallets here are placeholder names ("S", "M1", "HOT"), never real-looking
addresses, and the transfers are hand-written to exercise one allocation rule
each. Real wallets are covered by tests/test_demo_cases.py on recorded responses.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from vaspfusion.chains.base import ProviderError, Transfer, sort_transfers
from vaspfusion.labels.lookup import Label

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
CHAIN = "toy"


def tx(n: int, frm: str, to: str, amount, minute: int, asset: str = "USDT") -> Transfer:
    """Transfer number `n`: `frm` pays `to` `amount` at T0 + `minute` minutes."""
    amount = Decimal(str(amount))
    stable = asset in ("USDT", "USDC")
    return Transfer(chain=CHAIN, tx_hash=f"tx{n}", block_time=T0 + timedelta(minutes=minute),
                    from_addr=frm, to_addr=to, asset=asset, amount=amount,
                    amount_usd=amount if stable else None, fee_payer=None,
                    asset_contract=f"{asset.lower()}-contract" if stable or "@" in asset else None)


class ToyProvider:
    """Answers like a chain adapter: earliest first, `since`, `limit`, `asset`."""
    chain = CHAIN
    traceable_assets = ("USDT", "USDC", "COIN")

    def __init__(self, transfers, fail=()):
        self.rows = sort_transfers(list(transfers))
        self.fail = set(fail)
        self.calls: list[tuple] = []

    def transfers(self, address, direction="both", since=None, limit=200, asset=None):
        self.calls.append((address, direction, since, asset))
        if address in self.fail:
            raise ProviderError(f"upstream failed for {address}")
        rows = [t for t in self.rows
                if (direction != "in" and t.from_addr == address)
                or (direction != "out" and t.to_addr == address)]
        if asset is not None:
            rows = [t for t in rows if t.asset == asset]
        if since is not None:
            rows = [t for t in rows if t.block_time >= since]
        return rows[:limit]


class ToyLabels:
    """labels = {"HOT": ("ExA", "exchange"), "D1": ("ExA", "exchange", "deposit", "explorer_tag")}"""

    def __init__(self, labels: dict | None = None):
        self.labels = {}
        for addr, spec in (labels or {}).items():
            entity, category = spec[0], spec[1]
            kind = spec[2] if len(spec) > 2 else "unknown"
            tier = spec[3] if len(spec) > 3 else "curated"
            self.labels[addr] = Label(address=addr, chain=CHAIN, entity=entity, category=category,
                                      kind=kind, tier=tier, source="toy", source_url=None,
                                      label=f"{entity} toy label",
                                      confidence=spec[4] if len(spec) > 4 else None,
                                      evidence=spec[5] if len(spec) > 5 else None,
                                      confidence_low=spec[6] if len(spec) > 6 else None,
                                      confidence_high=spec[7] if len(spec) > 7 else None,
                                      reasons=spec[8] if len(spec) > 8 else None)

    def lookup_many(self, pairs):
        return {(a, c): self.labels[a] for a, c in pairs if a in self.labels}
