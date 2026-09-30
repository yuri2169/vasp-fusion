"""Address validation and chain detection, checked against published test vectors
(EIP-55, BIP-173, BIP-350) and real addresses from the label store."""
import pytest

from vaspfusion.chains.addresses import (
    b58check_decode, detect_chain, keccak256, tron_hex_to_base58, validate,
)
from vaspfusion.chains.base import InvalidAddress

EIP55_VECTORS = [  # from the EIP-55 spec
    "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
    "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
    "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
    "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
]


def test_keccak256_known_digests():
    assert keccak256(b"").hex() == \
        "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    # the ERC-20 transfer(address,uint256) selector
    assert keccak256(b"transfer(address,uint256)")[:4].hex() == "a9059cbb"


@pytest.mark.parametrize("addr", EIP55_VECTORS)
def test_eip55_vectors_valid(addr):
    assert validate(addr, "ethereum")
    assert validate(addr.lower(), "ethereum")  # all-lowercase carries no checksum


def test_eip55_bad_checksum_rejected():
    bad = EIP55_VECTORS[0].replace("aAeb", "aaeb")
    assert not validate(bad, "ethereum")


def test_evm_shape_rejected():
    assert not validate("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAe", "ethereum")
    assert not validate("5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed", "ethereum")


@pytest.mark.parametrize("addr", [
    "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h",                        # real P2WPKH (mempool.space)
    "BC1QM34LSC65ZPW79LXES69ZKQMK6EE3EWF0J77S3H",                        # all upper is legal
    "bc1qaxyju6n2x2tednv8e7hgnhnz44vrfcmuhjxpfk",                        # real, from the label CSV
    "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0",   # BIP-350 taproot
    "1BoatSLRHtKNngkdXEeobR76b53LETtpyT",                                # P2PKH
    "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",                                # P2SH
])
def test_btc_valid(addr):
    assert validate(addr, "bitcoin")


@pytest.mark.parametrize("addr", [
    "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3H",                        # mixed case
    "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3j",                        # bad checksum
    "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqh2y7hd",   # bech32 checksum on v1 (BIP-350 invalid)
    "1BoatSLRHtKNngkdXEeobR76b53LETtpyU",                                # bad base58check
])
def test_btc_invalid(addr):
    assert not validate(addr, "bitcoin")


def test_tron_valid_and_invalid():
    assert validate("TMhJviFWiaxvqKLdng9dmsi1H5H5yTGEeu", "tron")
    assert not validate("TMhJviFWiaxvqKLdng9dmsi1H5H5yTGEev", "tron")
    assert not validate("1BoatSLRHtKNngkdXEeobR76b53LETtpyT", "tron")  # BTC version byte


def test_tron_hex_to_base58_roundtrip():
    hex_addr = "41809fcccce1043b749ad63cd4c6d8a761b6237655"
    b58 = tron_hex_to_base58(hex_addr)
    assert validate(b58, "tron")
    assert b58check_decode(b58).hex() == hex_addr
    # the USDT contract, as TronGrid shows it in both forms
    assert tron_hex_to_base58("41a614f803b6fd780986a42c78ec9c7f77e6ded13c") == \
        "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


def test_solana_shape():
    assert validate("So11111111111111111111111111111111111111112", "solana")
    assert not validate("So1111111111111111111111111111111111111111O", "solana")  # 'O' not base58


@pytest.mark.parametrize("addr,chain", [
    ("TMhJviFWiaxvqKLdng9dmsi1H5H5yTGEeu", "tron"),
    ("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed", "ethereum"),
    ("1BoatSLRHtKNngkdXEeobR76b53LETtpyT", "bitcoin"),
    ("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy", "bitcoin"),
    ("bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h", "bitcoin"),
    ("So11111111111111111111111111111111111111112", "solana"),
    ("  TMhJviFWiaxvqKLdng9dmsi1H5H5yTGEeu ", "tron"),
])
def test_detect_chain(addr, chain):
    assert detect_chain(addr) == chain


@pytest.mark.parametrize("addr", ["", "hello", "0x123", "TMhJviFWiaxvqKLdng9dmsi1H5H5yTGEev",
                                  "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3j"])
def test_detect_chain_rejects(addr):
    with pytest.raises(InvalidAddress):
        detect_chain(addr)
