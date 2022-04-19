import pytest

from eth_account import Account

from pons import AccountSigner, Address


def test_signer():
    acc = Account.create()
    signer = AccountSigner(acc)

    assert signer.address == Address.from_hex(acc.address)

    tx = dict(gas="0x3333", gasPrice="0x4444", nonce="0x5555", value="0x6666")
    sig = signer.sign_transaction(tx)
    assert isinstance(sig, bytes)
    assert len(sig) == 83
    # Packed transaction values
    # 0xf8 = 0xf7 + 1 -> start of a list, payload length in 1 byte
    # 0x51 -> payload length 81
    # 0x82 = 0x80 + 2 -> a value of 2 bytes
    # 0x5555 -> the value
    # 0x82 = 0x80 + 2 -> a value of 2 bytes
    # 0x4444 -> the value
    # 0x82 = 0x80 + 2 -> a value of 2 bytes
    # 0x3333 -> the value
    # 0x80 = 0x80 + 0 -> a value of 0 bytes
    # 0x82 = 0x80 + 2 -> a value of 2 bytes
    # 0x6666 -> the value
    # 0x80 = 0x80 + 0 -> a value of 0 bytes
    # ... signature values start (v, r, s)
    assert sig.startswith(bytes.fromhex("f8518255558244448233338082666680"))
