import numpy as np

from vaspfusion.detect.venn_abers import VennAbers


def _data(n, rng):
    s = rng.random(n)
    y = (rng.random(n) < s).astype(int)          # perfectly calibrated scores
    return s, y


def test_interval_is_ordered_and_merge_lies_inside():
    rng = np.random.default_rng(0)
    va = VennAbers().fit(*_data(2000, rng))
    p0, p1 = va.interval(np.array([0.05, 0.5, 0.95]))
    assert np.all(p0 <= p1 + 1e-12)
    m = VennAbers.merge(p0, p1)
    assert np.all((m >= p0 - 1e-12) & (m <= p1 + 1e-12))


def test_interval_narrows_with_more_calibration_data():
    rng = np.random.default_rng(1)
    small = VennAbers().fit(*_data(200, rng))
    large = VennAbers().fit(*_data(20_000, rng))
    q = np.linspace(0.1, 0.9, 9)
    lo_s, hi_s = small.interval(q)
    lo_l, hi_l = large.interval(q)
    assert np.mean(hi_l - lo_l) < np.mean(hi_s - lo_s)
