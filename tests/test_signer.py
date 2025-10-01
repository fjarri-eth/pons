from eth_account import Account
from eth_account.types import HexStr, TransactionDictType
from ethereum_rpc import Address

from pons import AccountSigner


def check_signer(signer: AccountSigner) -> None:
    tx: TransactionDictType = dict(
        gas=HexStr("0x3333"),
        gasPrice=HexStr("0x4444"),
        nonce=HexStr("0x5555"),
        value=HexStr("0x6666"),
    )
    sig = signer.sign_transaction(tx)
    assert isinstance(sig, bytes)
    # the length may vary depending on the integers in the signature (they're not padded)
    payload_length = sig[1]
    assert len(sig) == payload_length + 2  # 2 bytes for the header + length byte
    # Packed transaction values
    # 0xf8 = 0xf7 + 1 -> start of a list, payload length in 1 byte
    # <1 byte> -> payload length
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
    assert sig.startswith(bytes.fromhex(f"f8{payload_length:x}8255558244448233338082666680"))


def test_signer() -> None:
    acc = Account.create()
    signer = AccountSigner(acc)

    assert signer.address == Address.from_hex(acc.address)
    assert signer.account == acc
    assert signer.private_key == bytes(acc._private_key)

    check_signer(signer)


def test_random_signer() -> None:
    signer = AccountSigner.create()
    check_signer(signer)
