from typing import Optional

from ._abi_types import UInt, Int, Bytes, AddressType, String, Bool, Type, Struct


_PyInt = int


def uint(bits: _PyInt) -> UInt:
    """Returns the ``uint<bits>`` type."""
    return UInt(bits)


def int(bits: _PyInt) -> Int:
    """Returns the ``int<bits>`` type."""
    return Int(bits)


def bytes(size: Optional[_PyInt] = None) -> Bytes:
    """Returns the ``bytes<size>`` type, or ``bytes`` if ``size`` is ``None``."""
    return Bytes(size)


def struct(**kwargs: Type) -> Struct:
    """Returns the structure type with given fields."""
    return Struct(kwargs)


address: AddressType = AddressType()
"""
``address`` type.
"""

string: String = String()
"""``string`` type."""

bool: Bool = Bool()
"""``bool`` type."""
