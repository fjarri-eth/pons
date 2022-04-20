from typing import Optional

from ._abi_types import UInt, Int, Bytes, AddressType, String, Bool, Type, Struct


_py_int = int


def uint(bits: _py_int) -> UInt:
    """Returns the ``uint<bits>`` type."""
    return UInt(bits)


def int(bits: _py_int) -> Int:
    """Returns the ``int<bits>`` type."""
    return Int(bits)


def bytes(size: Optional[_py_int] = None) -> Bytes:
    """Returns the ``bytes<size>`` type, or ``bytes`` if ``size`` is ``None``."""
    return Bytes(size)


def struct(**kwargs: Type) -> Struct:
    """Returns the structure type with given fields."""
    return Struct(kwargs)


address = AddressType()
"""``address`` type."""

string = String()
"""``string`` type."""

bool = Bool()
"""``bool`` type."""
