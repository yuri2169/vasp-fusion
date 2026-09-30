import numpy as np
import pytest

from vaspfusion.eval.selective import risk_coverage


def test_perfect_ordering_has_zero_excess_aurc():
    r = risk_coverage(np.array([0.9, 0.8, 0.1]), np.array([True, True, False]), 3)
    assert r["e_aurc"] == pytest.approx(0.0, abs=1e-9)


def test_worst_ordering_has_the_known_aurc():
    # ordered by confidence: wrong, right, right -> risk 1, 1/2, 1/3
    r = risk_coverage(np.array([0.1, 0.8, 0.9]), np.array([True, True, False]), 3)
    assert r["aurc"] == pytest.approx((1 + 0.5 + 1 / 3) / 3, abs=1e-4)
    assert r["oracle_aurc"] == pytest.approx((0 + 0 + 1 / 3) / 3, abs=1e-4)


def test_coverage_is_measured_against_everything_evaluable():
    r = risk_coverage(np.array([0.9, 0.5]), np.array([True, False]), 4)
    assert r["max_coverage"] == pytest.approx(0.5)


def test_nothing_answered_is_reported_as_unavailable():
    assert risk_coverage(np.array([]), np.array([], dtype=bool), 5) == {"available": False}


def test_risk_controlled_threshold_answers_the_reliable_band_only():
    from vaspfusion.eval.selective import risk_controlled_threshold
    rng = np.random.default_rng(0)
    hi = rng.uniform(0.06, 0.9, 4000)            # reliable band: 99% correct
    lo = rng.uniform(0.0, 0.049, 4000)           # coin flips
    conf = np.concatenate([hi, lo])
    correct = np.concatenate([rng.random(4000) < 0.99, rng.random(4000) < 0.5])
    pol = risk_controlled_threshold(conf, correct, target_risk=0.05)
    assert pol["attainable"] and 0.04 <= pol["threshold"] <= 0.07
    assert pol["risk_upper_bound"] <= 0.05


def test_unattainable_target_answers_nothing():
    from vaspfusion.eval.selective import risk_controlled_threshold
    conf = np.linspace(0, 1, 500)
    pol = risk_controlled_threshold(conf, np.zeros(500, dtype=bool), target_risk=0.05)
    assert not pol["attainable"] and pol["threshold"] > 1.0


def test_class_conditional_policy_never_answers_an_unreliable_class():
    from vaspfusion.eval.selective import ANSWER_NOTHING, class_conditional_threshold
    rng = np.random.default_rng(1)
    conf = rng.uniform(0.0, 0.9, 6000)
    kinds = np.array(["residential"] * 4000 + ["vpn"] * 2000)
    correct = np.concatenate([rng.random(4000) < 0.99, np.zeros(2000, dtype=bool)])
    pol = class_conditional_threshold(conf, correct, kinds, target_risk=0.05)
    assert pol["threshold_map"]["vpn"] == ANSWER_NOTHING
    assert pol["threshold_map"]["residential"] < 0.1
    assert "*" in pol["threshold_map"]


def test_shared_exit_classes_unseen_in_calibration_abstain():
    from vaspfusion.eval.selective import ANSWER_NOTHING, class_conditional_threshold
    rng = np.random.default_rng(2)
    conf = rng.uniform(0, 0.9, 2000)
    pol = class_conditional_threshold(conf, rng.random(2000) < 0.99,
                                      np.array(["residential"] * 2000))
    for kind in ("vpn", "tor", "cdn"):
        assert pol["threshold_map"][kind] == ANSWER_NOTHING


def test_shared_exit_classes_are_never_answered_whatever_the_calibration_says():
    import numpy as np
    from vaspfusion.eval.selective import ANSWER_NOTHING, class_conditional_threshold
    conf = np.linspace(0.5, 0.99, 1000)
    ok = np.ones(1000, dtype=bool)                     # calibration claims all correct
    cls = np.array(["vpn|shared"] * 500 + ["residential|direct"] * 500)
    p = class_conditional_threshold(conf, ok, cls)
    assert p["threshold_map"]["vpn|shared"] == ANSWER_NOTHING
    assert p["threshold_map"]["residential|direct"] < ANSWER_NOTHING
