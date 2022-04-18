from ._solidity_types import UInt, Int, Bytes, AddressType, String, Bool


_py_int = int


def uint(bits: _py_int) -> UInt:
    """Returns the ``uint<bits>`` type."""
    return UInt(bits)


def int(bits: _py_int) -> Int:
    """Returns the ``int<bits>`` type."""
    return Int(bits)


def bytes(size: _py_int) -> Bytes:
    """Returns the ``bytes<size>`` type."""
    return Bytes(size)


address = AddressType()
"""``address`` type."""

string = String()
"""``string`` type."""

bool = Bool()
"""``bool`` type."""
