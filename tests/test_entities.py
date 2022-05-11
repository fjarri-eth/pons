import os

import pytest

from pons import Amount, Address, TxHash, Block, TxReceipt
from pons._entities import (
    encode_quantity,
    encode_data,
    encode_block,
    decode_quantity,
    decode_data,
    RPCDecodingError,
)


def test_amount():
    # Conversions
    assert Amount.wei(100).as_wei() == 100
    assert Amount.wei(100).as_gwei() == 100 / 10**9
    assert Amount.wei(100).as_ether() == 100 / 10**18
    assert Amount.gwei(100).as_wei() == 100 * 10**9
    assert Amount.ether(100).as_wei() == 100 * 10**18

    with pytest.raises(TypeError, match="Amount must be an integer, got float"):
        Amount.wei(100.0)

    # other constructors cast to integer
    assert Amount.gwei(100.0).as_wei() == 100 * 10**9
    assert Amount.ether(100.0).as_wei() == 100 * 10**18

    with pytest.raises(ValueError, match="Amount must be non-negative, got -100"):
        Amount.wei(-100)

    # Encoding
    assert Amount.wei(100).encode() == "0x64"
    assert Amount.decode("0x64") == Amount.wei(100)

    assert Amount.wei(100) + Amount.wei(50) == Amount.wei(150)
    assert Amount.wei(100) - Amount.wei(50) == Amount.wei(50)
    assert Amount.wei(100) * 2 == Amount.wei(200)
    assert Amount.wei(100) // 2 == Amount.wei(50)
    assert Amount.wei(100) > Amount.wei(50)
    assert not (Amount.wei(50) > Amount.wei(50))
    assert Amount.wei(100) >= Amount.wei(50)
    assert Amount.wei(50) >= Amount.wei(50)
    assert Amount.wei(50) < Amount.wei(100)
    assert not (Amount.wei(50) < Amount.wei(50))
    assert Amount.wei(50) <= Amount.wei(100)
    assert Amount.wei(50) <= Amount.wei(50)

    # The type is hashable
    amount_set = {Amount.wei(100), Amount.wei(100), Amount.wei(50)}
    assert len(amount_set) == 2

    class MyAmount(Amount):
        pass

    assert repr(Amount.wei(100)) == "Amount(100)"
    assert repr(MyAmount.wei(100)) == "MyAmount(100)"

    with pytest.raises(TypeError, match="Incompatible types: Amount and int"):
        Amount.wei(100) + 100

    # Type checking is strict, subclasses are considered different types
    with pytest.raises(TypeError, match="Incompatible types: Amount and MyAmount"):
        Amount.wei(100) + MyAmount.wei(100)

    with pytest.raises(TypeError, match="Expected an integer, got float"):
        Amount.wei(100) * 2.0

    with pytest.raises(TypeError, match="Expected an integer, got float"):
        Amount.wei(100) // 2.0


def test_address():

    random_addr = b"dv\xbbCQ,\xfe\xd0\xbfF\x8aq\x07OK\xf9\xa1i\x88("
    random_addr_checksum = "0x6476Bb43512CFed0bF468a71074F4bF9A1698828"

    assert bytes(Address(random_addr)) == random_addr
    assert bytes(Address.from_hex(random_addr_checksum)) == random_addr
    assert bytes(Address.from_hex(random_addr_checksum.lower())) == random_addr

    assert Address(random_addr).checksum == random_addr_checksum

    assert Address(random_addr).encode() == random_addr_checksum
    assert Address.decode(random_addr_checksum) == Address(random_addr)
    assert Address(random_addr) == Address(random_addr)
    assert Address(random_addr) != Address(os.urandom(20))

    class MyAddress(Address):
        pass

    assert str(Address(random_addr)) == random_addr_checksum
    assert repr(Address(random_addr)) == f"Address.from_hex({random_addr_checksum})"
    assert repr(MyAddress(random_addr)) == f"MyAddress.from_hex({random_addr_checksum})"

    # The type is hashable
    addr_set = {Address(random_addr), Address(os.urandom(20)), Address(random_addr)}
    assert len(addr_set) == 2

    with pytest.raises(TypeError, match="Address must be a bytestring, got str"):
        Address(random_addr_checksum)

    with pytest.raises(ValueError, match="Address must be 20 bytes long, got 19"):
        Address(random_addr[:-1])

    with pytest.raises(ValueError, match="Address must be 20 bytes long, got 19"):
        Address(random_addr[:-1])

    with pytest.raises(TypeError, match="Incompatible types: MyAddress and Address"):
        # For whatever reason the the values are switched places in `__eq__()`
        Address(random_addr) == MyAddress(random_addr)

    # This error comes from eth_utils, we don't care about the phrasing,
    # but want to detect if the type changes.
    with pytest.raises(ValueError):
        Address.from_hex(random_addr_checksum[:-1])

    with pytest.raises(RPCDecodingError, match="Address must be 20 bytes long, got 19"):
        Address.decode("0x" + random_addr[:-1].hex())


def test_typed_data():
    # This is not covered by Address tests, since it overrides those methods
    data = os.urandom(32)
    tx_hash = TxHash(data)
    assert repr(tx_hash) == f'TxHash(bytes.fromhex("{data.hex()}"))'
    assert tx_hash.encode() == "0x" + data.hex()


def test_typed_data_lengths():
    # Just try to create the corresponding types,
    # it will cover their respective length methods.
    # Everything else is in the base class which is tested elsewhere
    TxHash(os.urandom(32))


def test_tx_receipt():

    address = Address(os.urandom(20))

    tx_receipt = TxReceipt.decode(
        {
            "contractAddress": address.encode(),
            "status": "0x1",
            "gasUsed": "0x1234",
        }
    )

    assert tx_receipt.succeeded
    assert tx_receipt.contract_address == address
    assert tx_receipt.gas_used == 0x1234

    tx_receipt = TxReceipt.decode(
        {
            "contractAddress": None,
            "status": "0x0",
            "gasUsed": "0x1234",
        }
    )

    assert not tx_receipt.succeeded
    assert tx_receipt.contract_address is None
    assert tx_receipt.gas_used == 0x1234


def test_encode_decode_quantity():
    assert encode_quantity(100) == "0x64"
    assert decode_quantity("0x64") == 100

    with pytest.raises(RPCDecodingError, match="Encoded quantity must be a string"):
        decode_quantity(100)

    with pytest.raises(RPCDecodingError, match="Encoded quantity must start with `0x`"):
        decode_quantity("616263")

    with pytest.raises(RPCDecodingError, match="Could not convert encoded quantity to an integer"):
        decode_quantity("0xefgh")


def test_encode_decode_data():
    assert encode_data(b"abc") == "0x616263"
    assert decode_data("0x616263") == b"abc"

    with pytest.raises(RPCDecodingError, match="Encoded data must be a string"):
        decode_data(616263)

    with pytest.raises(RPCDecodingError, match="Encoded data must start with `0x`"):
        decode_data("616263")

    with pytest.raises(RPCDecodingError, match="Could not convert encoded data to bytes"):
        decode_data("0xefgh")


def test_encode_block():
    assert encode_block(Block.LATEST) == "latest"
    assert encode_block(Block.EARLIEST) == "earliest"
    assert encode_block(Block.PENDING) == "pending"
    assert encode_block(123) == "0x7b"
