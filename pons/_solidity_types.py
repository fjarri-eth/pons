from abc import ABC, abstractmethod
import re
from typing import Optional, Any, Union

from ._entities import Address


class Type(ABC):
    """The base type for Solidity types."""

    @abstractmethod
    def canonical_form(self) -> str:
        ...

    @abstractmethod
    def normalize(self, val) -> Any:
        ...

    @abstractmethod
    def denormalize(self, val) -> Any:
        ...

    def __str__(self):
        return self.canonical_form()

    def __getitem__(self, array_size: Union[int, Any]):
        # In Py3.10 they added EllipsisType which would work better here.
        # For now, relying on the documentation.
        if isinstance(array_size, int):
            return Array(self, array_size)
        elif array_size == ...:
            return Array(self, None)
        else:
            raise TypeError(f"Invalid array size specifier: {array_size}")


class UInt(Type):

    def __init__(self, bits: int):
        if bits <= 0 or bits > 256 or bits % 8 != 0:
            raise Exception(f"Incorrect uint bit size: {bits}")
        self._bits = bits

    def canonical_form(self):
        return f"uint{self._bits}"

    def _check_val(self, val):
        assert isinstance(val, int)
        assert val > 0
        assert val >> self._bits == 0

    def normalize(self, val):
        self._check_val(val)
        return val

    def denormalize(self, val):
        self._check_val(val)
        return val


class Int(Type):

    def __init__(self, bits: int):
        if bits <= 0 or bits > 256 or bits % 8 != 0:
            raise Exception(f"Incorrect int bit size: {bits}")
        self._bits = bits

    def canonical_form(self):
        return f"int{self._bits}"

    def _check_val(self, val):
        assert isinstance(val, int)
        assert (val + (1 << (self._bits - 1))) >> self._bits == 0

    def normalize(self, val):
        self._check_val(val)
        return val

    def denormalize(self, val):
        self._check_val(val)
        return val


class Bytes(Type):

    def __init__(self, size: Optional[int]):
        if size is not None and (size <= 0 or size > 32):
            raise Exception(f"Incorrect bytes size: {size}")
        self._size = size

    def canonical_form(self):
        return f"bytes{self._size if self._size else ''}"

    def _check_val(self, val):
        assert isinstance(val, bytes)
        assert self._size is None or len(val) == self._size

    def normalize(self, val):
        self._check_val(val)
        return val

    def denormalize(self, val):
        self._check_val(val)
        return val


class AddressType(Type):

    def canonical_form(self):
        return "address"

    def normalize(self, val):
        assert isinstance(val, Address)
        return val.as_checksum()

    def denormalize(self, val):
        return Address.from_hex(val)


class String(Type):

    def canonical_form(self):
        return "string"

    def _check_val(self, val):
        assert isinstance(val, str)

    def normalize(self, val):
        self._check_val(val)
        return val

    def denormalize(self, val):
        self._check_val(val)
        return val


class Bool(Type):

    def canonical_form(self):
        return "bool"

    def _check_val(self, val):
        assert isinstance(val, bool)

    def normalize(self, val):
        self._check_val(val)
        return val

    def denormalize(self, val):
        self._check_val(val)
        return val


class Array(Type):

    def __init__(self, element_type, size=None):
        self.element_type = element_type
        self.size = size

    def canonical_form(self):
        return self.element_type.canonical_form() + "[" + (str(self.size) if self.size else "") + "]"

    def normalize(self, val):
        if isinstance(val, (list, tuple)):
            assert self.size is None or len(val) == self.size
            return [self.element_type.normalize(item) for item in val]
        else:
            raise TypeError(f"Cannot normalize {val} as {self}")

    def denormalize(self, val):
        assert isinstance(val, (list, tuple))
        assert self.size is None or len(val) == self.size
        return [self.element_type.denormalize(item) for item in val]

    def __str__(self):
        return str(self.element_type) + "[" + (str(self.size) if self.size else "") + "]"


class Struct(Type):

    def __init__(self, fields):
        self.fields = fields

    def canonical_form(self):
        return "(" + ",".join(field.canonical_form() for field in self.fields.values()) + ")"

    def normalize(self, val):
        if isinstance(val, dict):
            assert val.keys() == self.fields.keys()
            return [tp.normalize(val[name]) for name, tp in self.fields.items()]
        elif isinstance(val, (list, tuple)):
            assert len(val) == len(self.fields)
            return [tp.normalize(item) for item, tp in zip(val, self.fields.values())]
        else:
            raise TypeError(f"Cannot normalize {val} as {self}")

    def denormalize(self, val):
        assert isinstance(val, (list, tuple))
        assert len(val) == len(self.fields)
        return {name: tp.denormalize(item) for item, (name, tp) in zip(val, self.fields.items())}

    def __str__(self):
        return "(" + ", ".join(str(tp) + " " + str(name) for name, tp in self.fields.items()) + ")"


_UINT_RE = re.compile(r"uint(\d+)")
_INT_RE = re.compile(r"int(\d+)")
_BYTES_RE = re.compile(r"bytes(\d+)?")

_NO_PARAMS = {
    'address': AddressType,
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


def dispatch_type(abi_entry):
    type_str = abi_entry['type']
    match = re.match(r"^(.*?)(\[(\d+)?\])?$", type_str)
    if not match:
        raise Exception(f"Incorrect type format: {type_str}")

    element_type_name = match.group(1)
    is_array = match.group(2)
    array_size = match.group(3)
    if array_size:
        array_size = int(array_size)

    if is_array:
        element_entry = dict(abi_entry)
        element_entry['type'] = element_type_name
        element_type = dispatch_type(element_entry)
        return Array(element_type, array_size)
    elif element_type_name == 'tuple':
        fields = {}
        for component in abi_entry['components']:
            fields[component['name']] = dispatch_type(component)
        return Struct(fields)
    else:
        return type_from_abi_string(element_type_name)


def dispatch_types(abi_entry):
    return {entry['name']: dispatch_type(entry) for entry in abi_entry}
