from abc import ABC, abstractmethod
import re
from typing import Optional


class Type(ABC):

    @abstractmethod
    def canonical_signature(self):
        pass

    def __str__(self):
        return self.canonical_signature()


class UInt(Type):

    def __init__(self, bits: int):
        if bits <= 0 or bits > 256 or bits % 8 != 0:
            raise Exception(f"Incorrect uint bit size: {bits}")
        self._bits = bits

    def canonical_signature(self):
        return f"uint{self._bits}"


class Int(Type):

    def __init__(self, bits: int):
        if bits <= 0 or bits > 256 or bits % 8 != 0:
            raise Exception(f"Incorrect int bit size: {bits}")
        self._bits = bits

    def canonical_signature(self):
        return f"int{self._bits}"


class Bytes(Type):

    def __init__(self, size: Optional[int]):
        if size is not None and (size <= 0 or size > 32):
            raise Exception(f"Incorrect bytes size: {size}")
        self._size = size

    def canonical_signature(self):
        return f"bytes{self._size if self._size else ''}"


class Address(Type):
    def canonical_signature(self):
        return "address"


class String(Type):
    def canonical_signature(self):
        return "string"


class Bool(Type):
    def canonical_signature(self):
        return "bool"


_UINT_RE = re.compile(r"uint(\d+)")
_INT_RE = re.compile(r"int(\d+)")
_BYTES_RE = re.compile(r"bytes(\d+)?")

_NO_PARAMS = {
    'address': Address,
    'string': String,
    'bool': Bool,
}

def type_from_abi_string(abi_string):
    if match := _UINT_RE.match(abi_string):
        return UInt(int(match.group(1)))
    elif match := _INT_RE.match(abi_string):
        return Int(int(match.group(1)))
    elif match := _BYTES_RE.match(abi_string):
        size = match.group(1)
        return Bytes(int(size) if size else None)
    elif abi_string in _NO_PARAMS:
        return _NO_PARAMS[abi_string]()
    else:
        raise Exception(f"Unknown type: {abi_string}")
