"""Rupees beside dollars: one real, dated, sourced rate (config/fx.yaml)."""
from datetime import date

import pytest

from vaspfusion import fx


def test_the_rate_on_file_is_dated_and_sourced():
    r = fx.usd_inr()
    assert r["rate"] > 0 and isinstance(r["as_of"], date)
    assert r["source_url"].startswith("https://www.rbi.org.in/")
    assert r["published"] >= r["as_of"] and r["accessed"] >= r["published"]


def test_basis_says_which_rate_whose_and_of_what_date():
    r = {"rate": 83.5, "as_of": date(2024, 3, 7), "name": "RBI reference rate"}
    assert fx.basis(r) == "₹ at 1 USD = ₹83.50, RBI reference rate, 7 Mar 2024"
    assert f"{fx.usd_inr()['rate']:.2f}" in fx.basis()


@pytest.mark.parametrize("n, text", [(0, "0"), (999, "999"), (1000, "1,000"), (99999, "99,999"),
                                     (100000, "1,00,000"), (1234567, "12,34,567"),
                                     (123456789, "12,34,56,789"), (-4050000, "-40,50,000")])
def test_indian_digit_grouping(n, text):
    assert fx.group_indian(n) == text


def test_rupees_are_the_dollars_times_the_rate_rounded_to_the_rupee():
    r = {"rate": 80.0, "as_of": date(2024, 1, 1), "name": "x"}
    assert fx.inr(1530, r) == "₹1,22,400"
    assert fx.inr(0.004, r) == "₹0"
    assert fx.inr("1122.22", r) == "₹89,778"


@pytest.mark.parametrize("text", [
    "usd_inr: {rate: 0, as_of: 2026-01-01, name: x, source: {title: t, url: u}}",
    "usd_inr: {rate: 90, name: x, source: {title: t, url: u}}",
    "usd_inr: {rate: 90, as_of: 2026-01-01, name: x}",
    "{}",
])
def test_a_rate_without_a_date_or_a_source_is_refused(tmp_path, text):
    p = tmp_path / "fx.yaml"
    p.write_text(text)
    with pytest.raises(fx.FxError):
        fx.usd_inr(p)


def test_print_form_for_the_pdfs_and_only_for_dollar_assets():
    r = {"rate": 80.0, "as_of": date(2024, 1, 1), "name": "RBI reference rate"}
    assert fx.beside(1530, "USDT", fx=r) == " (Rs 1,22,400)"
    assert fx.beside(0.36, "BTC", fx=r) == "" and fx.beside(None, "USDT", fx=r) == ""
    assert fx.basis(r, fx.PRINT) == "Rs at 1 USD = Rs 80.00, RBI reference rate, 1 Jan 2024"
