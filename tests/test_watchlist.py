import polars as pl

from vaspfusion.graph.watchlist import nearest_with_queued, parse_watchlist, paths, propagate

E = pl.DataFrame({"src": ["A", "B", "C", "E", "X"], "dst": ["B", "C", "D", "A", "Y"]})


def _hits(r):
    return {row["entity"]: (row["hops"], row["direction"]) for row in r.to_dicts()}


def test_spreads_both_ways_and_stops_at_max_hops():
    r = propagate(E, {"A": "seized"}, max_hops=2)
    assert _hits(r) == {"A": (0, "seed"), "B": (1, "downstream"),
                        "E": (1, "upstream"), "C": (2, "downstream")}
    assert r.filter(pl.col("entity") == "C")["risk"][0] == 0.25


def test_a_path_never_switches_direction():
    e = pl.DataFrame({"src": ["A", "Z"], "dst": ["B", "B"]})   # Z also pays B
    assert "Z" not in propagate(e, {"A": "s"}, max_hops=3)["entity"].to_list()


def test_hubs_are_reached_but_not_spread_through():
    e = pl.DataFrame({"src": ["A"] + ["H"] * 5, "dst": ["H"] + [f"c{i}" for i in range(5)]})
    r = propagate(e, {"A": "s"}, max_hops=3, hub_degree=3)
    assert r.filter(pl.col("entity") == "H")["is_hub"][0]
    assert not any(x.startswith("c") for x in r["entity"].to_list())


def test_result_does_not_depend_on_input_order_and_paths_lead_to_a_seed():
    r1 = propagate(E, {"A": "s", "C": "t"}, max_hops=3)
    r2 = propagate(E.reverse(), {"C": "t", "A": "s"}, max_hops=3)
    assert r1.equals(r2)
    assert paths(r1)["D"] == ["D", "C"]


def test_parse_watchlist_accepts_plain_and_labelled_lines():
    rows, bad = parse_watchlist("address,label\n1BoatSLRHtKNngkdXEeobR76b53LETtpyT,LockBit\n"
                                "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh\n\nnot an address!\n",
                                "watchlist")
    assert rows == [("1BoatSLRHtKNngkdXEeobR76b53LETtpyT", "LockBit"),
                    ("bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh", "watchlist")]
    assert bad == 1


def test_truncated_hits_still_include_every_queued_lead():
    r = propagate(E, {"A": "list"}, max_hops=3)
    far = r.get_column("entity").to_list()[-1]
    got = nearest_with_queued(r, {far}, limit=1).get_column("entity").to_list()
    assert got == [r.get_column("entity")[0], far]
    assert nearest_with_queued(r, set(), limit=1).height == 1
