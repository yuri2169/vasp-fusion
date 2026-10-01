"""Label lookup: fixture DB for behaviour, the real DB for three known rows."""
from pathlib import Path

import pytest

from vaspfusion.labels.lookup import DEFAULT_DB, Label, LabelStore, lookup, lookup_batch


@pytest.fixture(scope="module")
def store(fixture_db):
    s = LabelStore(fixture_db[0])
    yield s
    s.close()


def test_mixed_case_evm_input_finds_the_lowercased_row(store):
    hit = store.lookup("0x0639556F03714A74a5fEEaF5736a4A64fF70D206", "cronos")
    assert isinstance(hit, Label)
    assert (hit.entity, hit.category, hit.tier) == ("Bitget", "exchange", "published_por")
    assert hit.is_vasp


def test_evm_chain_falls_back_to_chain_agnostic_rows(store):
    # The Dune spellbook lists CoinDCX's EVM wallets without a chain.
    hit = store.lookup("0x37B6BD5FECE5B88B6E8E825196BCC868A2FEED51", "bsc")
    assert hit.entity == "CoinDCX" and hit.chain == "evm"


def test_tron_lookup_is_case_sensitive(store):
    assert store.lookup("TAa8e7U7seCy7NcZ52xYVQXXybFfwvsUxz", "tron").entity == "Bitget"
    assert store.lookup("taa8e7u7secy7ncz52xyvqxxybffwvsuxz", "tron") is None


def test_unknown_address_is_none(store):
    assert store.lookup("TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf", "tron") is None


def test_sanctioned_is_not_a_vasp(store):
    hit = store.lookup("TA3941uFAvmVibSkQ6fMJXxmaSNovX86mz", "tron")
    assert hit.category == "sanctioned" and not hit.is_vasp


def test_lookup_many_returns_hits_keyed_by_the_input(store):
    pairs = [("0x975D9BD9928F398C7E01F6BA236816FA558CD94B", "ethereum"),
             ("TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf", "tron"),
             ("12T8i8tpeczk5JGf8ppZf1w6SFBRwEa9y4", "bitcoin")]
    hits = store.lookup_many(pairs)
    assert set(hits) == {pairs[0], pairs[2]}
    assert hits[pairs[0]].category == "swap_service"


def test_search_by_entity_and_filters(store):
    total, items = store.search("coindcx")
    assert total == 3 and {i.entity for i in items} == {"CoinDCX"}
    total, items = store.search("", category="swap_service")
    assert total == 1 and items[0].entity == "ChangeNOW"
    total, items = store.search("TAa8e7U7")
    assert total == 1 and items[0].chain == "tron"


def test_seeds_are_the_chains_exchange_wallets_in_a_fixed_order(store):
    seeds = store.seeds("tron")
    assert [(l.entity, l.address) for l in seeds] == sorted((l.entity, l.address) for l in seeds)
    assert {l.entity for l in seeds} >= {"Bitget", "CoinDCX"}
    assert all(l.category == "exchange" and l.chain == "tron" for l in seeds)
    assert "TA3941uFAvmVibSkQ6fMJXxmaSNovX86mz" not in {l.address for l in seeds}   # OFAC
    assert store.seeds("dogecoin") == []


def test_a_label_survives_a_round_trip_through_its_dict():
    from vaspfusion.labels.lookup import Label
    scored = Label("TDEP", "tron", "OKX", "exchange", "deposit", "derived", "vaspfusion-discover",
                   None, "OKX deposit address", 0.9, "Sweep rule.", 0.88, 0.93,
                   '{"basis": "model", "high": 0.98, "low": 0.93, "p": 0.95, "reasons": '
                   '[{"feature": "n_out", "text": "1 outgoing transfer", "weight": 0.2}], '
                   '"scored_by": "cross-fit:block 1"}')
    d = scored.as_dict()
    assert d["model"]["p"] == 0.95 and d["model"]["basis"] == "model"
    assert d["model"]["reasons"] == [{"feature": "n_out", "text": "1 outgoing transfer",
                                      "weight": 0.2}]
    assert Label.from_dict(d).as_dict() == d
    assert Label.from_dict({**d, "query_chain": "tron"}).confidence_low == 0.88
    plain = Label("T1", "tron", "OKX", "exchange", "hot", "curated", "x", None, None)
    assert Label.from_dict(plain.as_dict()) == plain
    old = {k: v for k, v in plain.as_dict().items() if k in (
        "address", "chain", "entity", "category", "kind", "tier", "source", "source_url", "label")}
    assert Label.from_dict(old) == plain            # a row recorded before B4


def test_non_deposit_lists_a_chains_labels_that_are_not_deposit_addresses(store):
    rows = store.non_deposit("tron")
    assert rows and [l.address for l in rows] == sorted(l.address for l in rows)
    assert all(l.chain == "tron" and l.kind != "deposit" and l.tier != "derived" for l in rows)
    assert {l.address for l in store.seeds("tron")} <= {l.address for l in rows}
    assert store.non_deposit("dogecoin") == []


def test_by_tier_lists_one_tier_of_one_chain_by_address(store):
    por = store.by_tier("tron", "published_por")
    assert [l.address for l in por] == ["TAa8e7U7seCy7NcZ52xYVQXXybFfwvsUxz"]
    assert all(l.tier == "curated" and l.chain == "tron" for l in store.by_tier("tron", "curated"))
    assert store.by_tier("tron", "derived") == []


def test_module_level_helpers_accept_a_db_path(fixture_db):
    db = fixture_db[0]
    assert lookup("TAWK8YMnn7yAfnQRyvjiBv9ksocFt9qNdR", "tron", db=db).entity == "CoinDCX"
    assert len(lookup_batch([("TAWK8YMnn7yAfnQRyvjiBv9ksocFt9qNdR", "tron")], db=db)) == 1


# --------------------------------------------------------------- the real DB
real = pytest.mark.skipif(not Path(DEFAULT_DB).exists(), reason="run `make labels` first")


@real
@pytest.mark.parametrize("address,chain,entity,category", [
    ("TAa8e7U7seCy7NcZ52xYVQXXybFfwvsUxz", "tron", "Bitget", "exchange"),
    ("12T8i8tpeczk5JGf8ppZf1w6SFBRwEa9y4", "bitcoin", "CoinDCX", "exchange"),
    ("0x975D9BD9928F398C7E01F6BA236816FA558CD94B", "ethereum", "ChangeNOW", "swap_service"),
])
def test_real_db_finds_known_addresses(address, chain, entity, category):
    hit = lookup(address, chain)
    assert (hit.entity, hit.category) == (entity, category)


@real
def test_real_db_exchange_count_matches_the_source():
    with LabelStore(DEFAULT_DB) as s:
        stats = s.stats()
        from_sources = s.con.execute("SELECT count(*) FROM labels WHERE category = 'exchange' "
                                     "AND tier <> 'derived'").fetchone()[0]
    # 27.7k exchange rows upstream + Dune, plus the Etherscan Exchange-tag rows. Deposit
    # addresses derived by `make discover` come on top and grow with every run.
    assert 36_000 <= from_sources <= 38_000
    assert stats["by_category"]["swap_service"] > 0
    assert stats["by_category"]["custodial_wallet"] > 0
