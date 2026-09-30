from vaspfusion.attribute.confidence import interval, significance_strength


def test_interval_narrows_as_evidence_accumulates():
    widths = [interval(0.6, n) for n in (1, 4, 16, 64)]
    assert widths == sorted(widths, reverse=True)
    assert widths[0] > widths[-1]


def test_interval_is_bounded():
    for conf in (0.0, 0.01, 0.5, 0.99, 1.0):
        for n in (0, 1, 10, 10_000):
            assert 0.02 <= interval(conf, n) <= 0.45


def test_strength_needs_both_significance_and_magnitude():
    strong = significance_strength(1e-12, 4.0)
    assert strong > 0.99
    assert significance_strength(1e-12, 0.0) < 0.01
    assert significance_strength(1.0, 4.0) < 0.01
