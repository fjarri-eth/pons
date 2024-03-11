import os

import pytest

from pons import Address, Amount
from pons._serialization import StructuringError, structure


def test_structure_into_typed_quantity():
    assert structure(Amount, "0x123") == Amount(0x123)

    with pytest.raises(
        StructuringError, match="The value must be a 0x-prefixed hex-encoded integer"
    ):
        structure(Amount, "abc")


def test_structure_into_int():
    assert structure(int, "0x123") == 0x123

    with pytest.raises(
        StructuringError, match="The value must be a 0x-prefixed hex-encoded integer"
    ):
        structure(int, "abc")


def test_structure_into_typed_data():
    address = os.urandom(20)
    assert structure(Address, "0x" + address.hex()) == Address(address)

    with pytest.raises(StructuringError, match="The value must be a 0x-prefixed hex-encoded data"):
        structure(Address, "abc")

    # The error text is weird
    with pytest.raises(
        StructuringError, match=r"non-hexadecimal number found in fromhex\(\) arg at position 0"
    ):
        structure(Address, "0xzz")
