"""The case-file narrative names an address only when the engine did."""
import numpy as np

from vaspfusion.explain.narrative import build_narrative

CAND = {"ip": "198.18.68.229", "asn": 64540, "asn_type": "residential", "country": "US",
        "confidence": 0.02}


def _text(status, note=""):
    return build_narrative(["max_n_outputs"], np.array([2.0]), np.array([30.0]), np.array([2.0]),
                           attribution={"candidates": [CAND], "status": status, "note": note})


def test_withheld_lead_is_not_described_as_attributed():
    t = _text("suppressed", "This actor was seen through VPN, Tor or CDN exits.")
    assert "Announced from" not in t and "198.18.68.229" not in t
    assert "No address is named. This actor was seen through VPN" in t


def test_answered_lead_names_its_address():
    assert "Announced from 198.18.68.229 (AS64540, residential, US)" in _text("ok")
