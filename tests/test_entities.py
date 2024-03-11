import os

import pytest

from pons import Address, Amount, BlockHash, TxHash
from pons._entities import LogTopic


def test_amount():
    # Conversions
    val = 100
    assert Amount.wei(val).as_wei() == val
    assert Amount.wei(val).as_gwei() == val / 10**9
    assert Amount.wei(val).as_ether() == val / 10**18
    assert Amount.gwei(val).as_wei() == val * 10**9
    assert Amount.ether(val).as_wei() == val * 10**18

    with pytest.raises(TypeError, match="Amount must be an integer, got float"):
        Amount.wei(100.0)

    # other constructors cast to integer
    assert Amount.gwei(100.0).as_wei() == 100 * 10**9
    assert Amount.ether(100.0).as_wei() == 100 * 10**18

    with pytest.raises(ValueError, match="Amount must be non-negative, got -100"):
        Amount.wei(-100)

    assert Amount.wei(100) + Amount.wei(50) == Amount.wei(150)
    assert Amount.wei(100) - Amount.wei(50) == Amount.wei(50)
    assert Amount.wei(100) * 2 == Amount.wei(200)
    assert Amount.wei(100) // 2 == Amount.wei(50)
    assert Amount.wei(100) > Amount.wei(50)
    assert not Amount.wei(50) > Amount.wei(50)
    assert Amount.wei(100) >= Amount.wei(50)
    assert Amount.wei(50) >= Amount.wei(50)
    assert Amount.wei(50) < Amount.wei(100)
    assert not Amount.wei(50) < Amount.wei(50)
    assert Amount.wei(50) <= Amount.wei(100)
    assert Amount.wei(50) <= Amount.wei(50)

    # The type is hashable
    amount_set = {Amount.wei(100), Amount.wei(100), Amount.wei(50)}
    assert amount_set == {Amount.wei(100), Amount.wei(50)}

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

    random_addr2 = os.urandom(20)

    assert bytes(Address(random_addr)) == random_addr
    assert bytes(Address.from_hex(random_addr_checksum)) == random_addr
    assert bytes(Address.from_hex(random_addr_checksum.lower())) == random_addr

    assert Address(random_addr).checksum == random_addr_checksum

    assert Address(random_addr) == Address(random_addr)
    assert Address(random_addr) != Address(os.urandom(20))

    class MyAddress(Address):
        pass

    assert str(Address(random_addr)) == random_addr_checksum
    assert repr(Address(random_addr)) == f"Address.from_hex({random_addr_checksum})"
    assert repr(MyAddress(random_addr)) == f"MyAddress.from_hex({random_addr_checksum})"

    # The type is hashable
    addr_set = {Address(random_addr), Address(random_addr2), Address(random_addr)}
    assert addr_set == {Address(random_addr), Address(random_addr2)}

    with pytest.raises(TypeError, match="Address must be a bytestring, got str"):
        Address(random_addr_checksum)

    with pytest.raises(ValueError, match="Address must be 20 bytes long, got 19"):
        Address(random_addr[:-1])

    with pytest.raises(ValueError, match="Address must be 20 bytes long, got 19"):
        Address(random_addr[:-1])

    with pytest.raises(TypeError, match="Incompatible types: MyAddress and Address"):
        # For whatever reason the the values are switched places in `__eq__()`
        assert Address(random_addr) == MyAddress(random_addr)

    # This error comes from eth_utils, we don't care about the phrasing,
    # but want to detect if the type changes.
    with pytest.raises(ValueError):  # noqa: PT011
        Address.from_hex(random_addr_checksum[:-1])


def test_typed_data():
    # This is not covered by Address tests, since it overrides those methods
    data = os.urandom(32)
    tx_hash = TxHash(data)
    assert repr(tx_hash) == f'TxHash(bytes.fromhex("{data.hex()}"))'


def test_typed_data_lengths():
    # Just try to create the corresponding types,
    # it will cover their respective length methods.
    # Everything else is in the base class which is tested elsewhere
    TxHash(os.urandom(32))
    BlockHash(os.urandom(32))
    LogTopic(os.urandom(32))
