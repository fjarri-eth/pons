from abc import ABC, abstractmethod
from functools import cached_property
import re
from typing import Optional, Any, Union, Iterable, Mapping, Dict

from ._entities import Address


class Type(ABC):
    """The base type for Solidity types."""

    @property
    @abstractmethod
    def canonical_form(self) -> str:
        """
        Returns the type as a string in the canonical form (for ``eth_abi`` consumption).
        """
        ...

    @abstractmethod
    def normalize(self, val) -> Any:
        """
        Checks and possibly normalizes the value making it ready to be passed
        to ``eth_abi.encode_single()`` for encoding.
        """
        ...

    @abstractmethod
    def denormalize(self, val) -> Any:
        """
        Checks the result of ``eth_abi.decode_single()``
        and wraps it in a specific type, if applicable.
        """
        ...

    def __str__(self):
        return self.canonical_form

    def __getitem__(self, array_size: Union[int, Any]):
        # In Py3.10 they added EllipsisType which would work better here.
        # For now, relying on the documentation.
        if isinstance(array_size, int):
            return Array(self, array_size)
        elif array_size == ...:
            return Array(self, None)
        else:
            raise TypeError(f"Invalid array size specifier type: {type(array_size).__name__}")


class UInt(Type):
    """
    Corresponds to the Solidity ``uint<bits>`` type.
    """

    def __init__(self, bits: int):
        if bits <= 0 or bits > 256 or bits % 8 != 0:
            raise ValueError(f"Incorrect `uint` bit size: {bits}")
        self._bits = bits

    @property
    def canonical_form(self):
        return f"uint{self._bits}"

    def _check_val(self, val):
        # `bool` is a subclass of `int`, but we would rather be more strict
        # and prevent possible bugs.
        if not isinstance(val, int) or isinstance(val, bool):
            raise TypeError(
                f"`{self.canonical_form}` must correspond to an integer, got {type(val).__name__}"
            )
        if val < 0:
            raise ValueError(
                f"`{self.canonical_form}` must correspond to a non-negative integer, got {val}"
            )
        if val >> self._bits != 0:
            raise ValueError(
                f"`{self.canonical_form}` must correspond to an unsigned integer "
                f"under {self._bits} bits, got {val}"
            )

    def normalize(self, val):
        self._check_val(val)
        return int(val)

    def denormalize(self, val):
        self._check_val(val)
        return val

    def __eq__(self, other):
        return isinstance(other, UInt) and self._bits == other._bits


class Int(Type):
    """
    Corresponds to the Solidity ``int<bits>`` type.
    """

    def __init__(self, bits: int):
        if bits <= 0 or bits > 256 or bits % 8 != 0:
            raise ValueError(f"Incorrect `int` bit size: {bits}")
        self._bits = bits

    @property
    def canonical_form(self):
        return f"int{self._bits}"

    def _check_val(self, val):
        # `bool` is a subclass of `int`, but we would rather be more strict
        # and prevent possible bugs.
        if not isinstance(val, int) or isinstance(val, bool):
            raise TypeError(
                f"`{self.canonical_form}` must correspond to an integer, got {type(val).__name__}"
            )
        if (val + (1 << (self._bits - 1))) >> self._bits != 0:
            raise ValueError(
                f"`{self.canonical_form}` must correspond to a signed integer "
                f"under {self._bits} bits, got {val}"
            )

    def normalize(self, val):
        self._check_val(val)
        return val

    def denormalize(self, val):
        self._check_val(val)
        return val

    def __eq__(self, other):
        return isinstance(other, Int) and self._bits == other._bits


class Bytes(Type):
    """
    Corresponds to the Solidity ``bytes<size>`` type.
    """

    def __init__(self, size: Optional[int] = None):
        if size is not None and (size <= 0 or size > 32):
            raise ValueError(f"Incorrect `bytes` size: {size}")
        self._size = size

    @property
    def canonical_form(self):
        return f"bytes{self._size if self._size else ''}"

    def _check_val(self, val):
        if not isinstance(val, bytes):
            raise TypeError(
                f"`{self.canonical_form}` must correspond to a bytestring, "
                f"got {type(val).__name__}"
            )
        if self._size is not None and len(val) != self._size:
            raise ValueError(f"Expected {self._size} bytes, got {len(val)}")

    def normalize(self, val):
        self._check_val(val)
        return val

    def denormalize(self, val):
        self._check_val(val)
        return val

    def __eq__(self, other):
        return isinstance(other, Bytes) and self._size == other._size


class AddressType(Type):
    """
    Corresponds to the Solidity ``address`` type.
    Not to be confused with :py:class:`~pons.Address` which represents an address value.
    """

    @property
    def canonical_form(self):
        return "address"

    def normalize(self, val):
        if not isinstance(val, Address):
            raise TypeError(
                f"`address` must correspond to an `Address`-type value, "
                f"got {type(val).__name__}"
            )
        return bytes(val)

    def denormalize(self, val):
        return Address.from_hex(val)

    def __eq__(self, other):
        return isinstance(other, AddressType)


class String(Type):
    """
    Corresponds to the Solidity ``string`` type.
    """

    @property
    def canonical_form(self):
        return "string"

    def _check_val(self, val):
        if not isinstance(val, str):
            raise TypeError(
                f"`string` must correspond to a `str`-type value, got {type(val).__name__}"
            )

    def normalize(self, val):
        self._check_val(val)
        return val

    def denormalize(self, val):
        self._check_val(val)
        return val

    def __eq__(self, other):
        return isinstance(other, String)


class Bool(Type):
    """
    Corresponds to the Solidity ``bool`` type.
    """

    @property
    def canonical_form(self):
        return "bool"

    def _check_val(self, val):
        if not isinstance(val, bool):
            raise TypeError(
                f"`bool` must correspond to a `bool`-type value, got {type(val).__name__}"
            )

    def normalize(self, val):
        self._check_val(val)
        return val

    def denormalize(self, val):
        self._check_val(val)
        return val

    def __eq__(self, other):
        return isinstance(other, Bool)


class Array(Type):
    """
    Corresponds to the Solidity array (``[<size>]``) type.
    """

    def __init__(self, element_type: Type, size: Optional[int] = None):
        self._element_type = element_type
        self._size = size

    @cached_property
    def canonical_form(self):
        return (
            self._element_type.canonical_form + "[" + (str(self._size) if self._size else "") + "]"
        )

    def _check_val(self, val):
        if not isinstance(val, Iterable):
            raise TypeError(f"Expected an iterable, got {type(val).__name__}")
        if self._size is not None and len(val) != self._size:
            raise ValueError(f"Expected {self._size} elements, got {len(val)}")

    def normalize(self, val):
        self._check_val(val)
        return [self._element_type.normalize(item) for item in val]

    def denormalize(self, val):
        self._check_val(val)
        return [self._element_type.denormalize(item) for item in val]

    def __eq__(self, other):
        return (
            isinstance(other, Array)
            and self._element_type == other._element_type
            and self._size == other._size
        )


class Struct(Type):
    """
    Corresponds to the Solidity struct type.
    """

    def __init__(self, fields: Mapping[str, Type]):
        self._fields = fields

    @cached_property
    def canonical_form(self):
        return "(" + ",".join(field.canonical_form for field in self._fields.values()) + ")"

    def _check_val(self, val):
        if not isinstance(val, Iterable):
            raise TypeError(f"Expected an iterable, got {type(val).__name__}")
        if len(val) != len(self._fields):
            raise ValueError(f"Expected {len(self._fields)} elements, got {len(val)}")

    def normalize(self, val):
        if isinstance(val, Mapping):
            if val.keys() != self._fields.keys():
                raise ValueError(
                    f"Expected fields {list(self._fields.keys())}, got {list(val.keys())}"
                )
            return [tp.normalize(val[name]) for name, tp in self._fields.items()]
        else:
            self._check_val(val)
            return [tp.normalize(item) for item, tp in zip(val, self._fields.values())]

    def denormalize(self, val):
        self._check_val(val)
        return {name: tp.denormalize(item) for item, (name, tp) in zip(val, self._fields.items())}

    def __str__(self):
        # Overriding  the `Type`'s implementation because we want to show the field names too
        return "(" + ", ".join(str(tp) + " " + str(name) for name, tp in self._fields.items()) + ")"

    def __eq__(self, other):
        return (
            isinstance(other, Struct)
            and self._fields == other._fields
            # structs with the same fields but in different order are not equal
            and list(self._fields) == list(other._fields)
        )


_UINT_RE = re.compile(r"uint(\d+)")
_INT_RE = re.compile(r"int(\d+)")
_BYTES_RE = re.compile(r"bytes(\d+)?")

_NO_PARAMS = {
    "address": AddressType(),
    "string": String(),
    "bool": Bool(),
}


def type_from_abi_string(abi_string: str) -> Type:
    if match := _UINT_RE.match(abi_string):
        return UInt(int(match.group(1)))
    elif match := _INT_RE.match(abi_string):
        return Int(int(match.group(1)))
    elif match := _BYTES_RE.match(abi_string):
        size = match.group(1)
        return Bytes(int(size) if size else None)
    elif abi_string in _NO_PARAMS:
        return _NO_PARAMS[abi_string]
    else:
        raise ValueError(f"Unknown type: {abi_string}")


def dispatch_type(abi_entry: Mapping[str, Any]) -> Type:
    type_str = abi_entry["type"]
    match = re.match(r"^([\w\d\[\]]*?)(\[(\d+)?\])?$", type_str)
    if not match:
        raise ValueError(f"Incorrect type format: {type_str}")

    element_type_name = match.group(1)
    is_array = match.group(2)
    array_size = match.group(3)
    if array_size:
        array_size = int(array_size)

    if is_array:
        element_entry = dict(abi_entry)
        element_entry["type"] = element_type_name
        element_type = dispatch_type(element_entry)
        return Array(element_type, array_size)
    elif element_type_name == "tuple":
        fields = {}
        for component in abi_entry["components"]:
            fields[component["name"]] = dispatch_type(component)
        return Struct(fields)
    else:
        return type_from_abi_string(element_type_name)


def dispatch_types(abi_entry: Iterable[Dict[str, Any]]) -> Dict[str, Type]:
    # Since we are returning a dictionary, need to be sure we don't silently merge entries
    names = [entry["name"] for entry in abi_entry]
    if len(names) != len(set(names)):
        raise ValueError("All ABI entries must have distinct names")
    return {entry["name"]: dispatch_type(entry) for entry in abi_entry}
