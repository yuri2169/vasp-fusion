"""Explorer deposit tags filed upstream under another exchange's name: the on-chain check
and what the loader does with its verdicts. The label rows are real, copied verbatim; the
transfers are made up for each verdict."""
import shutil
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from vaspfusion.chains import ProviderError, Transfer
from vaspfusion.chains.base import TransferList
from vaspfusion.labels.load import build_labels
from vaspfusion.labels.lookup import Label
from vaspfusion.labels.sources import SOURCES, TAG_CHECKED_SOURCE, by_source
from vaspfusion.labels.tagcheck import (COLUMNS, check_address, read_checks, summary,
                                        tag_owner, write_csv)

FIX = Path(__file__).parent.parent / "fixtures" / "labels"
HEAD = "address,network,entity,label,category,source,source_url,confidence,last_updated\n"
TAIL = "entity,eth-labels,https://github.com/dawsbot/eth-labels,medium,2026-07-17\n"
A = "0x000f9f5f6db6d63bb64bb55d58272a1ce660fd90"
B = "0x002983b0776e37da1c2f316e6253e9c1b740b6f8"
C = "0x002aa9b6c16b25d6b4425602c6a90d18105150ce"
ROWS = (f"{A},ethereum,bilaxy,Binance Dep: 0x000f9f5F6db6d63bB64bb55d58272A1ce660fD90,{TAIL}"
        f"{B},ethereum,bilaxy,Binance Dep: {B},{TAIL}"
        f"{C},ethereum,bilaxy,Binance Dep: {C},{TAIL}")
BINANCE_HOT = "0x28c6c06298d514db089934071355e5743bf21d60"
OTHER_HOT = "0x0d0707963952f2fba59dd06f2b425ace40b492fe"


def _label(entity, kind="hot", tier="curated", category="exchange"):
    return Label("0x", "ethereum", entity, category, kind, tier, "cex-list", None, entity,
                 None, None)


class Labels:
    def __init__(self, known):
        self.known = known

    def lookup(self, address, chain):
        return self.known.get(address)


class Provider:
    def __init__(self, rows=(), complete=True, error=None):
        self.rows, self.complete, self.error = list(rows), complete, error

    def transfers(self, address, direction, limit):
        if self.error:
            raise ProviderError(self.error)
        return TransferList(self.rows, complete=self.complete)


def _t(src, dst, day=1):
    return Transfer("ethereum", f"0x{day:064x}", datetime(2024, 3, day, tzinfo=timezone.utc),
                    src, dst, "USDT", Decimal("10"), Decimal("10"), None)


KNOWN = Labels({BINANCE_HOT: _label("Binance"), OTHER_HOT: _label("Gate.io")})


def test_the_owner_is_read_from_a_deposit_tag_only():
    assert tag_owner("Binance Dep: 0xabc") == "Binance"
    assert tag_owner("Binance 14") is None and tag_owner("") is None


def test_an_address_that_pays_into_the_exchanges_wallet_is_confirmed():
    rows = [_t("0xcustomer", A, 1), _t(A, BINANCE_HOT, 2), _t(A, BINANCE_HOT, 3),
            _t(A, "0xelse", 4)]
    r = check_address(Provider(rows), KNOWN, A, "ethereum", "Binance")
    assert (r["verdict"], r["seen"], r["n_rows"], r["n_out"]) == ("confirmed", 1, 4, 3)
    assert (r["top_recipient"], r["top_recipient_entity"]) == (BINANCE_HOT, "Binance")
    assert r["first_seen"] == "2024-03-01T00:00:00Z" and r["tag"] == "Binance Dep"


def test_used_without_a_labelled_recipient_is_used_not_confirmed():
    r = check_address(Provider([_t("0xcustomer", A)]), KNOWN, A, "ethereum", "Binance")
    assert (r["verdict"], r["n_out"], r["top_recipient"]) == ("used", 0, "")
    r = check_address(Provider([_t(A, "0xunlabelled")]), KNOWN, A, "ethereum", "Binance")
    assert (r["verdict"], r["top_recipient_entity"]) == ("used", "")


def test_paying_mostly_into_another_exchanges_wallet_contradicts_the_tag():
    rows = [_t(A, OTHER_HOT, 1), _t(A, OTHER_HOT, 2), _t(A, BINANCE_HOT, 3)]
    r = check_address(Provider(rows), KNOWN, A, "ethereum", "Binance")
    assert (r["verdict"], r["top_recipient_entity"]) == ("contradicted", "Gate.io")


def test_a_deposit_address_as_top_recipient_proves_nothing():
    known = Labels({BINANCE_HOT: _label("Binance", kind="deposit", tier="explorer_tag")})
    r = check_address(Provider([_t(A, BINANCE_HOT)]), known, A, "ethereum", "Binance")
    assert r["verdict"] == "used"


def test_never_used_and_could_not_be_read_are_different_verdicts():
    assert check_address(Provider(), KNOWN, A, "ethereum", "Binance")["verdict"] == "unused"
    r = check_address(Provider(error="HTTP 502"), KNOWN, A, "ethereum", "Binance")
    assert (r["verdict"], r["seen"], r["error"]) == ("unread", "", "HTTP 502")


def test_the_check_file_round_trips(tmp_path):
    rows = [check_address(Provider([_t(A, BINANCE_HOT)]), KNOWN, A, "ethereum", "Binance"),
            check_address(Provider(), KNOWN, B, "ethereum", "Binance")]
    write_csv(rows, tmp_path / "checks" / "x.csv")
    back = read_checks(tmp_path / "checks")
    assert back[(A, "ethereum")]["verdict"] == "confirmed"
    assert back[(B, "ethereum")]["verdict"] == "unused"
    assert (tmp_path / "checks" / "x.csv").read_text().splitlines()[0] == ",".join(COLUMNS)
    assert summary(rows)["checked"] == 2 and read_checks(tmp_path / "nowhere") == {}


@pytest.fixture
def wa(tmp_path):
    folder = tmp_path / "wa"
    shutil.copytree(FIX / "wa", folder)
    with (folder / "ethereum.csv").open("a") as f:
        f.write(ROWS)
    return folder


def _checks(tmp_path, verdicts):
    rows = [{**dict.fromkeys(COLUMNS, ""), "address": a, "chain": "ethereum",
             "tag": "Binance Dep", "verdict": v,
             "top_recipient": BINANCE_HOT if v == "confirmed" else ""}
            for a, v in verdicts.items()]
    write_csv(rows, tmp_path / "checks" / "binance_dep_ethereum.csv")
    return tmp_path / "checks"


def _held(db, address):
    with duckdb.connect(str(db), read_only=True) as con:
        return con.execute("SELECT entity, category, kind, tier, source, evidence FROM labels "
                           "WHERE address = ? AND chain = 'ethereum'", [address]).fetchone()


def test_without_a_check_the_rows_stay_as_filed(wa, tmp_path):
    stats = build_labels(tmp_path / "l.duckdb", wa, FIX / "dune.csv")
    assert _held(tmp_path / "l.duckdb", A)[:5] == ("Bilaxy", "entity", "deposit",
                                                    "explorer_tag", "eth-labels")
    assert stats["tag_checks"]["unresolved"] == 3 and stats["tag_checks"]["unchecked"] == 3
    assert stats["tag_checks"]["loaded"] == 0


def test_only_a_checked_and_uncontradicted_tag_is_named_after_the_tag(wa, tmp_path):
    checks = _checks(tmp_path, {A: "confirmed", B: "used", C: "unused"})
    db = tmp_path / "l.duckdb"
    stats = build_labels(db, wa, FIX / "dune.csv", checks_dir=checks)
    entity, category, kind, tier, source, evidence = _held(db, A)
    assert (entity, category, kind, tier, source) == ("Binance", "exchange", "deposit",
                                                      "explorer_tag", TAG_CHECKED_SOURCE)
    assert BINANCE_HOT in evidence
    assert _held(db, B)[:2] == ("Binance", "exchange") and BINANCE_HOT not in _held(db, B)[5]
    assert _held(db, C)[:2] == ("Bilaxy", "entity")          # never used: left as filed
    assert stats["tag_checks"] == {"unresolved": 3, "loaded": 2, "unchecked": 0,
                                   "confirmed": 1, "used": 1, "contradicted": 0, "unused": 1,
                                   "unread": 0}


@pytest.mark.parametrize("verdict", ["contradicted", "unread", "unused"])
def test_a_contradicted_unread_or_unused_tag_is_left_as_filed(wa, tmp_path, verdict):
    db = tmp_path / "l.duckdb"
    build_labels(db, wa, FIX / "dune.csv", checks_dir=_checks(tmp_path, {A: verdict}))
    assert _held(db, A)[:2] == ("Bilaxy", "entity")


def test_the_checked_tags_are_a_source_of_their_own_with_a_licence():
    name, obtained, licence, url = SOURCES[TAG_CHECKED_SOURCE]
    assert licence.startswith("MIT") and "eth-labels" in url
    row, = by_source([(TAG_CHECKED_SOURCE, "explorer_tag", 7)])
    assert (row["source"], row["labels"], row["tiers"]) == (TAG_CHECKED_SOURCE, 7,
                                                           {"explorer_tag": 7})
