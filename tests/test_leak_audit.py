import numpy as np
import polars as pl

from vaspfusion.eval.leak_audit import audit


def test_audit_flags_a_planted_identifier_leak_and_passes_a_clean_identifier():
    rng = np.random.default_rng(0)
    n = 20_000
    y = (rng.random(n) < 0.05).astype(int)
    leaky = np.where(y == 1, rng.integers(0, 100, n), rng.integers(100, 10_000, n))
    clean = rng.integers(0, 10_000, n)
    df = pl.DataFrame({"label": y,
                       "leaky_id": [f"{v:05d}" for v in leaky],
                       "clean_id": [f"{v:05d}" for v in clean]})
    out = audit(df, "label", ["leaky_id", "clean_id"], None, [])
    assert out["fields"]["leaky_id__rank"]["lift"] > 3
    assert out["fields"]["clean_id__rank"]["lift"] < 1.30
    assert "leaky_id__rank" in out["strict_over_gate"]
