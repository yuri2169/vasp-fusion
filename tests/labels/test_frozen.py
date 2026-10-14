"""The USDT freeze list: replaying the contract's events into the set frozen now, the
dated snapshot, and lookups."""
import csv
import json

from vaspfusion.labels import frozen as FZ

T1 = "TNPeeaaFB7K9cmo4uQpcU32zGK8G1NYqeL"
T2 = "TLDtPqEhVPGUXmVfJEqtAHU6p5pyDqdrVgoJ"[:34]
E1 = "0xa614f803b6fd780986a42c78ec9c7f77e6ded13c"


def ev(event, address, t, chain="tron", tx=None, index=0):
    return {"chain": chain, "event": event, "address": address, "time_ms": t,
            "block": t // 1000, "tx": tx or f"tx{t}{event[0]}", "index": index}


def test_replay_adds_then_removes_in_time_order():
    events = [ev("AddedBlackList", T1, 1_000), ev("AddedBlackList", T2, 2_000),
              ev("RemovedBlackList", T1, 3_000)]
    now = FZ.replay(events)
    assert set(now) == {(T2, "tron")}
    assert now[(T2, "tron")]["frozen_at_ms"] == 2_000


def test_a_freeze_after_a_release_dates_from_the_newest_freeze():
    events = [ev("AddedBlackList", T1, 1_000), ev("RemovedBlackList", T1, 2_000),
              ev("AddedBlackList", T1, 5_000, tx="again")]
    now = FZ.replay(list(reversed(events)))          # the order given does not matter
    assert now[(T1, "tron")]["frozen_at_ms"] == 5_000
    assert now[(T1, "tron")]["tx_hash"] == "again"


def test_a_second_add_keeps_the_first_date():
    events = [ev("AddedBlackList", T1, 1_000, tx="first"), ev("AddedBlackList", T1, 4_000)]
    assert FZ.replay(events)[(T1, "tron")]["tx_hash"] == "first"


def test_released_lists_addresses_taken_off_and_not_put_back():
    events = [ev("AddedBlackList", T1, 1_000), ev("RemovedBlackList", T1, 2_000),
              ev("AddedBlackList", T2, 1_500)]
    assert FZ.released(events) == [(T1, "tron")]


def test_snapshot_round_trip_and_lookup(tmp_path):
    events = [ev("AddedBlackList", T1, 1_600_000_000_000),
              ev("AddedBlackList", E1, 1_500_000_000_000, chain="ethereum")]
    path = tmp_path / "usdt_frozen.csv"
    FZ.write_snapshot(FZ.replay(events), path, {"fetched_at": "2026-10-14T00:00:00Z"})
    rows = list(csv.DictReader(path.open()))
    assert [r["address"] for r in rows] == [E1, T1]          # sorted by chain, address
    assert rows[1]["frozen_at"] == "2020-09-13T12:26:40Z"
    assert rows[1]["issuer"] == "Tether" and rows[1]["asset"] == "USDT"
    meta = json.loads(path.with_suffix(".json").read_text())
    assert meta["counts"] == {"ethereum": 1, "tron": 1}
    fl = FZ.FreezeList.load(path)
    hit = fl.lookup(T1, "tron")
    assert hit["frozen_at"] == "2020-09-13T12:26:40Z" and hit["issuer"] == "Tether"
    assert fl.lookup(E1.upper().replace("0X", "0x"), "ethereum") is not None
    assert fl.lookup(E1, "bsc") is None                 # USDT on Ethereum only
    assert fl.lookup(T2, "tron") is None
    assert fl.many([(T1, "tron"), (T2, "tron")]).keys() == {(T1, "tron")}
    assert fl.stats()["total"] == 2


def test_a_missing_snapshot_is_an_empty_list(tmp_path):
    fl = FZ.FreezeList.load(tmp_path / "none.csv")
    assert fl.lookup(T1, "tron") is None and fl.stats()["total"] == 0


def test_mark_words():
    assert FZ.mark_text({"issuer": "Tether", "frozen_at": "2024-08-03T10:00:00Z"}) == \
        "Frozen by Tether on 3 Aug 2024"


def test_the_sample_is_seeded_and_covers_both_ways():
    frozen = {(f"a{i}", "tron"): {} for i in range(50)}
    gone = [(f"b{i}", "tron") for i in range(50)]
    s1 = FZ.check_sample(frozen, gone, n=5, seed=7)
    assert s1 == FZ.check_sample(frozen, gone, n=5, seed=7)
    assert sum(1 for _, _, want in s1 if want) == 5 and len(s1) == 10


def test_the_tracked_snapshot_if_present_is_well_formed():
    fl = FZ.FreezeList.load()
    if fl.stats()["total"] == 0:
        return
    meta = json.loads(FZ.DEFAULT_CSV.with_suffix(".json").read_text())
    for key in ("source", "contracts", "fetched_at", "cutoff", "counts", "check", "licence"):
        assert key in meta
    assert meta["check"]["agreed"] + meta["check"]["disagreed"] == meta["check"]["checked"]
