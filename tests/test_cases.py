"""Cases: one queue row is one operation (link_campaigns); these check the
member table that makes that visible."""
import polars as pl

from vaspfusion.graph.build import member_stats

E = pl.DataFrame({"src": ["A", "B", "A", "C", "X"], "dst": ["B", "C", "X", "A", "A"],
                  "value": [100, 40, 999, 7, 5], "n_tx": [2, 1, 9, 1, 1]})


def test_member_stats_count_only_money_inside_the_case():
    s = {m["entity"]: m for m in member_stats(E, ["A", "B", "C"])}
    assert s["A"] == {"entity": "A", "n_tx": 2, "value_out": 100, "value_in": 7}
    assert s["B"] == {"entity": "B", "n_tx": 1, "value_out": 40, "value_in": 100}
    assert s["C"] == {"entity": "C", "n_tx": 1, "value_out": 7, "value_in": 40}


def test_member_stats_keeps_member_order_and_zero_fills():
    assert [m["entity"] for m in member_stats(E, ["C", "Q"])] == ["C", "Q"]
    assert member_stats(E, ["C", "Q"])[1]["value_in"] == 0
