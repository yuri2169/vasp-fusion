"""Normalisation rules for the label store. Every case is a real row from
research/data (wallet-attribution or the Dune spellbook extract)."""
import pytest

from vaspfusion.labels.normalize import (
    address_chain,
    canonical_entity, infer_kind, map_category, normalize_address, normalize_chain,
    tier_for,
)


@pytest.mark.parametrize("raw,want", [
    ("TRX", "tron"), ("BTC", "bitcoin"), ("EVM", "evm"), ("XRP", "xrp"),
    ("ethereum", "ethereum"), ("bitcoin-cash", "bitcoin-cash"),
])
def test_chain_names_are_normalised(raw, want):
    assert normalize_chain(raw) == want


def test_evm_addresses_are_lowercased():
    assert (normalize_address("0x0639556F03714A74a5fEEaF5736a4A64fF70D206", "cronos")
            == "0x0639556f03714a74a5feeaf5736a4a64ff70d206")
    assert (normalize_address(" 0x37B6BD5FECE5B88B6E8E825196BCC868A2FEED51", "evm")
            == "0x37b6bd5fece5b88b6e8e825196bcc868a2feed51")


@pytest.mark.parametrize("addr,chain", [
    ("TAa8e7U7seCy7NcZ52xYVQXXybFfwvsUxz", "tron"),
    ("12T8i8tpeczk5JGf8ppZf1w6SFBRwEa9y4", "bitcoin"),
])
def test_base58_addresses_keep_their_case(addr, chain):
    assert normalize_address(addr, chain) == addr


@pytest.mark.parametrize("source,want", [
    ("defillama-cex", "published_por"),
    ("eth-labels", "explorer_tag"),
    ("cex-list+eth-labels", "curated"),
    ("defillama-cex+eth-labels", "published_por"),
    ("ofac-sdn", "curated"),
    ("mew-ethereum-lists", "curated"),
    ("dune-spellbook", "curated"),
    ("etherscan public tag + dune-spellbook", "curated"),
    ("wazirx.com post-incident report + etherscan + dune-spellbook", "curated"),
])
def test_tier_follows_the_strongest_source(source, want):
    assert tier_for(source) == want


@pytest.mark.parametrize("raw,label,want", [
    ("bitget", "Bitget Dep: 0x000483C56FE99127fbd62da5D8b899a159116dc1", "Bitget"),
    ("OKX (OKEx)", "OKX (OKEx) (proof-of-reserves)", "OKX"),
    ("HTX (Huobi)", "HTX (Huobi) (proof-of-reserves)", "HTX"),
    ("exchange", "ChangeNOW 10", "ChangeNOW"),
    ("changenow", "ChangeNOW: Hot Wallet 1", "ChangeNOW"),
    ("blocked", "Tornado.Cash: 50,000 cDAI 2", "Tornado.Cash"),
    ("token-contract", "Vela Exchange: VELA Token", "Vela Exchange"),
    ("fiat-gateway", "Uphold.com", "Uphold"),
    ("celsius-network", "Celsius 1", "Celsius"),
    ("cex-io", "CEX.IO 2", "CEX.IO"),
    ("anchorage-digital", "Anchorage Digital: Custodian 1", "Anchorage Digital"),
    ("altcoin-trader", "AltCoinTrader: Celsius Deposit 1", "AltCoinTrader"),
    ("CoinDCX", "CoinDCX 3", "CoinDCX"),
    ("exchange", "OKX Dep: 0x46C...A2851", "OKX"),
    ("exchange", "Crypto.com 44", "Crypto.com"),
    ("exchange", "exchange", "Unidentified exchange"),
    ("exchange", "Sideshift: Deposit Funder 1", "SideShift"),
    ("bilaxy", "Binance Dep: 0x000f9f5F6db6d63bB64bb55d58272A1ce660fD90", "Bilaxy"),
])
def test_entity_names_are_canonical(raw, label, want):
    assert canonical_entity(raw, label) == want


@pytest.mark.parametrize("raw,entity,label,want,raw_entity", [
    ("entity", "ChangeNOW", "ChangeNOW: Hot Wallet 1", "swap_service", ""),
    ("entity", "BitGo", "BitGo: MultiSig 3", "custodial_wallet", ""),
    ("entity", "Paxos", "Paxos: USDP Token", "entity", ""),
    ("entity", "Wirex", "Wirex: Deployer", "entity", ""),
    ("exchange", "Vela Exchange", "Vela Exchange: VELA Token", "entity", ""),
    ("exchange", "Binance", "Binance Hot Wallet", "exchange", ""),
    ("exchange", "Nexo", "Nexo 1", "exchange", ""),
    ("mixer", "Tornado.Cash", "Tornado.Cash: 50,000 cDAI 2", "mixer", ""),
    ("sanctioned", "OFAC SDN", "OFAC sanctioned (USDT)", "sanctioned", ""),
    ("bridge", "THORSwap", "THORSwap: RouterV2", "bridge", ""),
    # Etherscan's generic "Exchange" tag: the owner is in the label, and it is a VASP
    ("entity", "OKX", "OKX Dep: 0x46C...A2851", "exchange", "exchange"),
    ("entity", "Bilaxy", "Bilaxy: Deposit Funder", "exchange", "exchange"),
    ("entity", "Celsius", "Celsius 20", "custodial_wallet", "exchange"),
    ("entity", "SideShift", "Sideshift: Deposit Funder 1", "swap_service", "exchange"),
    ("entity", "SideShift", "Sideshift: svXAI Token", "entity", "exchange"),
    # Slug and label disagree on the owner (bilaxy vs "Binance Dep"): not promoted
    ("entity", "Bilaxy", "Binance Dep: 0x000f9f5F6db6d63bB64bb55d58272A1ce660fD90",
     "entity", "bilaxy"),
])
def test_categories_separate_swap_services_and_custodians(raw, entity, label, want,
                                                         raw_entity):
    assert map_category(raw, entity, label, raw_entity) == want


@pytest.mark.parametrize("label,source,want", [
    ("Bitget Dep: 0x000483C56FE99127fbd62da5D8b899a159116dc1", "eth-labels", "deposit"),
    ("CoinSwitch Binance Deposit 1", "dune-spellbook", "deposit"),
    ("ChangeNOW: Deposit Funder 1", "eth-labels", "hot"),
    ("Revolut: Cold Wallet", "eth-labels", "cold"),
    ("Binance Hot Wallet", "eth-labels", "hot"),
    ("CoinDCX (proof-of-reserves)", "defillama-cex", "reserve"),
    ("Celsius Network: CEL Treasury Reserve", "eth-labels", "reserve"),
    ("CoinDCX 3", "dune-spellbook", "unknown"),
])
def test_wallet_kind_is_read_from_the_label(label, source, want):
    assert infer_kind(label, source) == want


# Real rows: base.csv "Coinbase 35" (address truncated upstream) and the OFAC SDN
# entry the 0xB10C list files as XBT although the address is a Tron address.
@pytest.mark.parametrize("address,chain,want", [
    ("TAa8e7U7seCy7NcZ52xYVQXXybFfwvsUxz", "tron", "tron"),            # valid as filed
    ("12T8i8tpeczk5JGf8ppZf1w6SFBRwEa9y4", "bitcoin", "bitcoin"),
    ("0x0639556F03714A74a5fEEaF5736a4A64fF70D206", "cronos", "cronos"),
    ("0x1985EA6E...2Fdb25c87", "base", None),                          # truncated: unusable
    ("TUCsTq7TofTCJRRoHk6RvhMoS2mJLm5Yzq", "bitcoin", "tron"),         # misfiled: re-file
    ("r3AEihLNr81VYUf5PdfH5wLPqtJJyJs6yY", "xrp", "xrp"),              # no validator: kept
])
def test_address_chain_drops_unusable_and_refiles_misfiled(address, chain, want):
    assert address_chain(address, chain) == want
