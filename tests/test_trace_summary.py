"""What a trace saw and what it followed: counted where each decision is made
(trace.py), reported by `trace_summary`. Toy transfers (see tracekit.py)."""
from tracekit import CHAIN, ToyLabels, ToyProvider, tx
from vaspfusion.trace import TraceConfig, context_rows, trace, trace_summary

EX = {"HOT": ("ExA", "exchange", "hot", "curated")}


def run(transfers, labels=None, fail=(), **cfg):
    return trace("S", CHAIN, ToyProvider(transfers, fail=fail),
                 ToyLabels(labels if labels is not None else EX), TraceConfig(**cfg))


def reasons(summary):
    return {r["reason"]: r["wallet_ids"] for r in summary["not_followed"]}


# S pays M1 1000; M1 had paid OLD before the money arrived, then pays HOT 600 and X 300,
# and sends a dust transfer to P. F funded S.
LINE = [tx(1, "S", "M1", 1000, 10), tx(2, "M1", "OLD", 50, 0), tx(3, "M1", "HOT", 600, 20),
        tx(4, "M1", "X", 300, 30), tx(5, "M1", "P", "0.01", 40), tx(6, "F", "S", 2000, 1)]


def test_every_row_of_every_listing_read_is_seen_once():
    r = run(LINE)
    s = trace_summary(r)
    # S's outgoing and incoming listings, M1's and X's since the money arrived. A labelled
    # wallet (HOT) is not read, nor is a funder at the hop limit (F), and tx2 is older than
    # the money, so it was never asked for
    assert {t.tx_hash for t in r.seen} == {"tx1", "tx3", "tx4", "tx5", "tx6"}
    assert s["transfers_seen"] == 5
    assert set(r.read) == {"S", "M1", "X"}
    assert s["wallets_read"] == 3


def test_followed_and_context_add_up_to_seen():
    r = run(LINE)
    s = trace_summary(r)
    assert s["transfers_followed"] == 4            # tx1, tx3, tx4 out; tx6 in
    assert {t.tx_hash for t in context_rows(r)} == {"tx5"}
    assert s["transfers_followed"] + len(context_rows(r)) == s["transfers_seen"]
    assert s["transfers_dust"] == 1


def test_a_wallet_seen_only_through_dust_is_listed_as_below_the_dust_limit():
    s = trace_summary(run(LINE))
    assert reasons(s)["dust"] == ["P"]


def test_each_wallet_the_money_reached_is_followed_or_has_one_reason():
    r = run(LINE)
    s = trace_summary(r)
    assert s["wallets_followed"] == 3              # S, M1, X (read; it sent nothing on)
    assert reasons(s)["labelled"] == ["HOT"]
    assert reasons(s)["depth_limit"] == ["F"]
    reached = {addr for (_side, addr) in r.nodes}
    listed = [w for row in s["not_followed"] if row["reason"] != "dust" for w in row["wallet_ids"]]
    assert len(listed) == len(set(listed))
    assert s["wallets_followed"] + len(listed) == len(reached)
    assert s["wallets_not_followed"] == sum(row["count"] for row in s["not_followed"])


def test_a_hub_is_read_and_not_followed():
    spray = [tx(100 + i, "HUB", f"C{i}", 10, 20 + i) for i in range(30)]
    s = trace_summary(run([tx(1, "S", "HUB", 1000, 10)] + spray, inbound_hops=0))
    assert reasons(s) == {"hub": ["HUB"]}
    assert s["wallets_read"] == 2 and s["wallets_followed"] == 1
    assert s["transfers_seen"] == 31 and s["transfers_followed"] == 1


def test_the_hop_limit_a_small_share_and_the_budget_each_have_their_reason():
    rows = [tx(1, "S", "A", 990, 0), tx(2, "S", "TINY", 5, 0), tx(3, "S", "B", 5, 0),
            tx(4, "A", "A2", 990, 5), tx(5, "A2", "A3", 990, 9)]
    s = trace_summary(run(rows, max_hops=2, inbound_hops=0))
    assert reasons(s) == {"small": ["B", "TINY"], "depth_limit": ["A2"]}
    s = trace_summary(run([tx(1, "S", "A", 600, 0), tx(2, "S", "B", 400, 0)],
                          max_nodes=1, inbound_hops=0))
    assert reasons(s) == {"budget": ["B"]}


def test_a_wallet_that_could_not_be_read_is_listed_as_such():
    s = trace_summary(run([tx(1, "S", "M1", 1000, 0)], fail={"M1"}, inbound_hops=0))
    assert reasons(s) == {"unreadable": ["M1"]}
    assert s["wallets_read"] == 1


def test_the_sentence_says_the_counts_in_an_officers_words():
    s = trace_summary(run(LINE))
    assert s["text"] == ("Followed 4 of 5 transfers seen. 3 wallets not followed: "
                         "1 below the dust limit, 1 already labelled (the trail ends there), "
                         "1 at the hop limit.")
    assert [row["text"] for row in s["not_followed"]] == [
        "1 below the dust limit", "1 already labelled (the trail ends there)",
        "1 at the hop limit"]
    quiet = trace_summary(run([tx(1, "S", "M1", 10, 0)], inbound_hops=0))
    assert quiet["text"] == "Followed 1 of 1 transfer seen. Every wallet the money reached was read."


def test_counting_changes_nothing_about_the_trace():
    a, b = run(LINE), run(LINE)
    trace_summary(a)
    assert a.edges == b.edges and a.stopped == b.stopped
    assert {k: (n.state, n.received, n.held) for k, n in a.nodes.items()} == \
        {k: (n.state, n.received, n.held) for k, n in b.nodes.items()}
