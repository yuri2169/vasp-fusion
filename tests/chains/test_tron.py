"""Tron adapter on recorded TronGrid responses for CoinDCX 1 (a Dune-spellbook label)."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from chainfix import load_fixture
from vaspfusion.chains.base import InvalidAddress, ProviderError
from vaspfusion.chains.tron import USDT, TronProvider

ADDR = "TGjpmhAFT6d7eBKvaFwPVN6H2pDKgLLZiw"          # CoinDCX 1
FIRST_USDT = "10c0ea77a51861b5440bf0f166cffa21686ba35126161ac27db26123e5273bba"


def provider(fetcher):
    return TronProvider(fetcher, page_size=3, key="")


def test_paging_and_merge(fixture_fetcher):
    f = fixture_fetcher("tron_usdt")
    rows = provider(f).transfers(ADDR, "both", limit=7)
    assert len(rows) == 7
    # 3 TRC-20 pages and 4 raw-transaction pages were followed by fingerprint
    assert f.transport.calls == 7
    assert [r.block_time for r in rows] == sorted(r.block_time for r in rows)
    assert all(ADDR in (r.from_addr, r.to_addr) for r in rows)
    assert {r.asset for r in rows} == {"USDT", "TRX"}


def test_usdt_row_matches_raw_fixture(fixture_fetcher):
    raw = next(x for page in load_fixture("tron_usdt")["responses"].values()
               for x in page["body"]["data"] if x.get("transaction_id") == FIRST_USDT)
    t = provider(fixture_fetcher("tron_usdt")).transfers(ADDR, "both", limit=7)[0]
    assert t.tx_hash == FIRST_USDT
    assert (t.from_addr, t.to_addr) == (raw["from"], raw["to"])
    assert t.amount == Decimal(raw["value"]) / 10 ** 6 == Decimal(750000)
    assert t.amount_usd == t.amount
    assert t.asset_contract == USDT
    assert t.block_time == datetime(2022, 6, 10, 16, 16, 54, tzinfo=timezone.utc)
    # the signer of the matching TriggerSmartContract, copied from the raw listing
    assert t.fee_payer == "TU7BbAsb8t371eMijQeiGXsiLvY1vZbsFs"


def test_trx_rows_are_successful_transfer_contracts_only(fixture_fetcher):
    rows = provider(fixture_fetcher("tron_usdt")).transfers(ADDR, "both", limit=7)
    trx = [r for r in rows if r.asset == "TRX"]
    assert len(trx) == 5
    assert all(r.fee_payer == r.from_addr and r.amount_usd is None for r in trx)
    # the TRC-10 (TransferAssetContract) and contract-call rows in the raw pages are skipped
    raw_ids = {x["txID"] for page in load_fixture("tron_usdt")["responses"].values()
               for x in page["body"]["data"] if "txID" in x
               and x["raw_data"]["contract"][0]["type"] != "TransferContract"}
    assert raw_ids and not raw_ids & {r.tx_hash for r in trx}
    dust = next(r for r in trx if r.tx_hash.startswith("0664e2f7"))
    assert dust.amount == Decimal("0.000001")


def test_direction_in_and_since(fixture_fetcher):
    since = datetime(2022, 7, 1, tzinfo=timezone.utc)
    rows = provider(fixture_fetcher("tron_since_in")).transfers(ADDR, "in", since=since, limit=4)
    assert len(rows) == 4
    assert all(r.to_addr == ADDR and r.block_time >= since for r in rows)
    usdt = [r for r in rows if r.asset == "USDT"]
    assert [r.amount for r in usdt] == [Decimal("149999.2")]


def test_offline_replay_identical(fixture_fetcher):
    live = provider(fixture_fetcher("tron_usdt")).transfers(ADDR, "both", limit=7)
    f2 = fixture_fetcher("tron_usdt", offline=True)
    again = provider(f2).transfers(ADDR, "both", limit=7)
    assert again == live
    assert f2.transport.calls == 0 and f2.stats["hits"] == 7


def test_offline_uncached_fails_loudly(fixture_fetcher):
    from vaspfusion.chains.base import CacheMiss
    with pytest.raises(CacheMiss):
        provider(fixture_fetcher("tron_usdt", offline=True)).transfers(ADDR, "out", limit=7)


def test_invalid_address(fixture_fetcher):
    with pytest.raises(InvalidAddress):
        provider(fixture_fetcher("tron_usdt")).transfers("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed")


def test_trongrid_error_body_is_fatal():
    from vaspfusion.chains.tron import _check
    with pytest.raises(ProviderError, match="bad address"):
        _check({"success": False, "error": "bad address"})
