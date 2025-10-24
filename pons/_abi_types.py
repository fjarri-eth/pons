# We need to have some module-private members in `Type`.
# ruff: noqa: SLF001

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from functools import cached_property
from types import EllipsisType
from typing import Any, cast

import eth_abi
from eth_abi.exceptions import DecodingError
from ethereum_rpc import Address, keccak

ABI_JSON = None | bool | int | float | str | Sequence["ABI_JSON"] | Mapping[str, "ABI_JSON"]
"""Values serializable to JSON."""

# Maximum bits in an `int` or `uint` type in Solidity.
MAX_INTEGER_BITS = 256

# Maximum size of a `bytes` type in Solidity.
MAX_BYTES_SIZE = 32


class ABIDecodingError(Exception):
    """Raised on an error when decoding a value in an Eth ABI encoded bytestring."""


ABIType = int | str | bytes | bool | list["ABIType"]
"""
Represents the argument type that can be received from ``eth_abi.decode()``,
or passed to ``eth_abi.encode()``.
"""


class Type(ABC):
    """The base type for Solidity types."""

    @property
    @abstractmethod
    def canonical_form(self) -> str:
        """Returns the type as a string in the canonical form (for ``eth_abi`` consumption)."""
        ...

    @abstractmethod
    def _normalize(self, val: Any) -> ABIType:
        """
        Checks and possibly normalizes the value making it ready to be passed
        to ``encode()`` for encoding.
        """
        ...

    @abstractmethod
    def _denormalize(self, val: ABIType) -> Any:
        """Checks the result of ``decode()`` and wraps it in a specific type, if applicable."""
        ...

    def encode(self, val: Any) -> bytes:
        """Encodes the given value in the contract ABI format."""
        return eth_abi.encode([self.canonical_form], [val])

    def encode_to_topic(self, val: Any) -> bytes:
        """Encodes the given value as an event topic."""
        # EVM uses a simpler encoding scheme for encoding values into event topics
        # because objects of reference types are just hashed,
        # and there is no need to unpack them later
        # (basically, all values are just concatenated without any lentgh labels).
        # Therefore we have to provide these methods
        # and cannot just use the functions from ``eth_abi``.

        # Before doing anything, normalize the value,
        # this will ensure the constituent values are actually valid.
        return self._encode_to_topic_outer(self._normalize(val))

    def _encode_to_topic_outer(self, val: Any) -> bytes:
        """Encodes a value of the outer indexed type."""
        # By default it's just the encoding of the value type.
        # May be overridden.
        return self.encode(val)

    def _encode_to_topic_inner(self, val: Any) -> bytes:
        """Encodes a value contained within an indexed array or struct."""
        # By default it's just the encoding of the value type.
        # May be overridden.
        return self.encode(val)

    def decode_from_topic(self, val: bytes) -> Any | None:
        """
        Decodes an encoded topic.
        Returns ``None`` if the decoding is impossible
        (that is, the original value was hashed).
        """
        # This method does not have inner/outer division, since all reference types are hashed,
        # and there's no need to go recursively into structs/arrays - we won't be able to recover
        # the values anyway.

        # By default it's just the decoding of the value type.
        # May be overridden.
        return self._denormalize(eth_abi.decode([self.canonical_form], val)[0])

    def __str__(self) -> str:
        return self.canonical_form

    def __getitem__(self, array_size: int | EllipsisType) -> "Array":
        # In Py3.10 they added EllipsisType which would work better here.
        # For now, relying on the documentation.
        if isinstance(array_size, int):
            return Array(self, array_size)
        if array_size == ...:
            return Array(self, None)
        raise TypeError(f"Invalid array size specifier type: {type(array_size).__name__}")


class UInt(Type):
    """Corresponds to the Solidity ``uint<bits>`` type."""

    def __init__(self, bits: int):
        if bits <= 0 or bits > MAX_INTEGER_BITS or bits % 8 != 0:
            raise ValueError(f"Incorrect `uint` bit size: {bits}")
        self._bits = bits

    @property
    def canonical_form(self) -> str:
        return f"uint{self._bits}"

    def _check_val(self, val: Any) -> int:
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
        return int(val)

    def _normalize(self, val: Any) -> int:
        return self._check_val(val)

    def _denormalize(self, val: ABIType) -> int:
        return self._check_val(val)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, UInt) and self._bits == other._bits

    def __hash__(self) -> int:
        return hash((type(self), self._bits))


class Int(Type):
    """Corresponds to the Solidity ``int<bits>`` type."""

    def __init__(self, bits: int):
        if bits <= 0 or bits > MAX_INTEGER_BITS or bits % 8 != 0:
            raise ValueError(f"Incorrect `int` bit size: {bits}")
        self._bits = bits

    @property
    def canonical_form(self) -> str:
        return f"int{self._bits}"

    def _check_val(self, val: Any) -> int:
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
        return int(val)

    def _normalize(self, val: Any) -> int:
        return self._check_val(val)

    def _denormalize(self, val: ABIType) -> int:
        return self._check_val(val)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Int) and self._bits == other._bits

    def __hash__(self) -> int:
        return hash((type(self), self._bits))


class Bytes(Type):
    """Corresponds to the Solidity ``bytes<size>`` type."""

    def __init__(self, size: None | int = None):
        if size is not None and (size <= 0 or size > MAX_BYTES_SIZE):
            raise ValueError(f"Incorrect `bytes` size: {size}")
        self._size = size

    @property
    def canonical_form(self) -> str:
        return f"bytes{self._size if self._size else ''}"

    def _check_val(self, val: Any) -> bytes:
        if not isinstance(val, bytes):
            raise TypeError(
                f"`{self.canonical_form}` must correspond to a bytestring, got {type(val).__name__}"
            )
        if self._size is not None and len(val) != self._size:
            raise ValueError(f"Expected {self._size} bytes, got {len(val)}")
        return val

    def _normalize(self, val: Any) -> bytes:
        return self._check_val(val)

    def _denormalize(self, val: ABIType) -> bytes:
        return self._check_val(val)

    def _encode_to_topic_outer(self, val: bytes) -> bytes:
        if self._size is None:
            # Dynamic `bytes` is a reference type and is therefore hashed.
            return keccak(val)
        # Sized `bytes` is a value type, falls back to the base implementation.
        return super()._encode_to_topic_outer(val)

    def _encode_to_topic_inner(self, val: bytes) -> bytes:
        if self._size is None:
            # Dynamic `bytes` is padded to a multiple of 32 bytes.
            padding_len = (32 - len(val)) % 32
            return val + b"\x00" * padding_len
        # Sized `bytes` is a value type, falls back to the base implementation.
        return super()._encode_to_topic_inner(val)

    def decode_from_topic(self, val: bytes) -> None | bytes:
        if self._size is None:
            # Cannot recover a hashed value.
            return None
        return super().decode_from_topic(val)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Bytes) and self._size == other._size

    def __hash__(self) -> int:
        return hash((type(self), self._size))


class AddressType(Type):
    """
    Corresponds to the Solidity ``address`` type.
    Not to be confused with :py:class:`ethereum_rpc.Address` which represents an address value.
    """

    @property
    def canonical_form(self) -> str:
        return "address"

    def _normalize(self, val: Any) -> str:
        if not isinstance(val, Address):
            raise TypeError(
                f"`address` must correspond to an `Address`-type value, got {type(val).__name__}"
            )
        return val.checksum

    def _denormalize(self, val: ABIType) -> Address:
        if not isinstance(val, str):
            raise TypeError(f"Expected a string to convert to `Address`, got {type(val).__name__}")
        return Address.from_hex(val)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, AddressType)

    def __hash__(self) -> int:
        return hash(type(self))


class String(Type):
    """Corresponds to the Solidity ``string`` type."""

    @property
    def canonical_form(self) -> str:
        return "string"

    def _check_val(self, val: Any) -> str:
        if not isinstance(val, str):
            raise TypeError(
                f"`string` must correspond to a `str`-type value, got {type(val).__name__}"
            )
        return val

    def _normalize(self, val: Any) -> str:
        return self._check_val(val)

    def _denormalize(self, val: ABIType) -> str:
        return self._check_val(val)

    def _encode_to_topic_outer(self, val: str) -> bytes:
        # `string` is encoded and treated as dynamic `bytes`
        return Bytes()._encode_to_topic_outer(val.encode())

    def _encode_to_topic_inner(self, val: str) -> bytes:
        # `string` is encoded and treated as dynamic `bytes`
        return Bytes()._encode_to_topic_inner(val.encode())

    def decode_from_topic(self, _val: bytes) -> None:
        # Dynamic `string` is hashed, so the value cannot be recovered.
        return None

    def __eq__(self, other: object) -> bool:
        return isinstance(other, String)

    def __hash__(self) -> int:
        return hash(type(self))


class Bool(Type):
    """Corresponds to the Solidity ``bool`` type."""

    @property
    def canonical_form(self) -> str:
        return "bool"

    def _check_val(self, val: Any) -> bool:
        if not isinstance(val, bool):
            raise TypeError(
                f"`bool` must correspond to a `bool`-type value, got {type(val).__name__}"
            )
        return val

    def _normalize(self, val: Any) -> bool:
        return self._check_val(val)

    def _denormalize(self, val: ABIType) -> bool:
        return self._check_val(val)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Bool)

    def __hash__(self) -> int:
        return hash(type(self))


class Array(Type):
    """Corresponds to the Solidity array (``[<size>]``) type."""

    def __init__(self, element_type: Type, size: None | int = None):
        self._element_type = element_type
        self._size = size

    @cached_property
    def canonical_form(self) -> str:
        return (
            self._element_type.canonical_form + "[" + (str(self._size) if self._size else "") + "]"
        )

    def _check_val(self, val: Any) -> Sequence[Any]:
        if not isinstance(val, Sequence):
            raise TypeError(f"Expected an iterable, got {type(val).__name__}")
        if self._size is not None and len(val) != self._size:
            raise ValueError(f"Expected {self._size} elements, got {len(val)}")
        return val

    def _normalize(self, val: Any) -> list[ABIType]:
        return [self._element_type._normalize(item) for item in self._check_val(val)]

    def _denormalize(self, val: ABIType) -> list[ABIType]:
        return [self._element_type._denormalize(item) for item in self._check_val(val)]

    def _encode_to_topic_outer(self, val: Any) -> bytes:
        return keccak(self._encode_to_topic_inner(val))

    def _encode_to_topic_inner(self, val: Any) -> bytes:
        return b"".join(self._element_type._encode_to_topic_inner(elem) for elem in val)

    def decode_from_topic(self, _val: Any) -> None:
        return None

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Array)
            and self._element_type == other._element_type
            and self._size == other._size
        )

    def __hash__(self) -> int:
        return hash((type(self), self._element_type, self._size))


class Struct(Type):
    """Corresponds to the Solidity struct type."""

    def __init__(self, fields: Mapping[str, Type]):
        self._fields = fields

    @cached_property
    def canonical_form(self) -> str:
        return "(" + ",".join(field.canonical_form for field in self._fields.values()) + ")"

    def _check_val(self, val: Any) -> Sequence[Any]:
        if not isinstance(val, Sequence):
            raise TypeError(f"Expected an iterable, got {type(val).__name__}")
        if len(val) != len(self._fields):
            raise ValueError(f"Expected {len(self._fields)} elements, got {len(val)}")
        return val

    def _normalize(self, val: Any) -> list[ABIType]:
        if isinstance(val, Mapping):
            if val.keys() != self._fields.keys():
                raise ValueError(
                    f"Expected fields {list(self._fields.keys())}, got {list(val.keys())}"
                )
            return [tp._normalize(val[name]) for name, tp in self._fields.items()]
        return [
            tp._normalize(item)
            for item, tp in zip(self._check_val(val), self._fields.values(), strict=True)
        ]

    def _denormalize(self, val: ABIType) -> dict[str, ABIType]:
        return {
            name: tp._denormalize(item)
            for item, (name, tp) in zip(self._check_val(val), self._fields.items(), strict=True)
        }

    def _encode_to_topic_outer(self, val: Any) -> bytes:
        return keccak(self._encode_to_topic_inner(val))

    def _encode_to_topic_inner(self, val: Any) -> bytes:
        return b"".join(
            tp._encode_to_topic_inner(elem)
            for elem, tp in zip(val, self._fields.values(), strict=True)
        )

    def decode_from_topic(self, _val: Any) -> None:
        return None

    def __str__(self) -> str:
        # Overriding  the `Type`'s implementation because we want to show the field names too
        return "(" + ", ".join(str(tp) + " " + str(name) for name, tp in self._fields.items()) + ")"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Struct)
            and self._fields == other._fields
            # structs with the same fields but in different order are not equal
            and list(self._fields) == list(other._fields)
        )

    def __hash__(self) -> int:
        return hash((type(self), tuple(self._fields.items())))


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
    if match := _INT_RE.match(abi_string):
        return Int(int(match.group(1)))
    if match := _BYTES_RE.match(abi_string):
        size = match.group(1)
        return Bytes(int(size) if size else None)
    if abi_string in _NO_PARAMS:
        return _NO_PARAMS[abi_string]
    raise ValueError(f"Unknown type: {abi_string}")


def dispatch_type(abi_entry: ABI_JSON) -> Type:
    # TODO (#83): use proper validation
    abi_entry_typed = cast("Mapping[str, Any]", abi_entry)

    type_str = abi_entry_typed["type"]
    match = re.match(r"^([\w\d\[\]]*?)(\[(\d+)?\])?$", type_str)
    if not match:
        raise ValueError(f"Incorrect type format: {type_str}")

    element_type_name = match.group(1)
    is_array = match.group(2)
    array_size = match.group(3)
    if array_size is not None:
        array_size = int(array_size)

    if is_array:
        element_entry = dict(abi_entry_typed)
        element_entry["type"] = element_type_name
        element_type = dispatch_type(element_entry)
        return Array(element_type, array_size)

    if element_type_name == "tuple":
        fields = {}
        for component in abi_entry_typed["components"]:
            fields[component["name"]] = dispatch_type(component)
        return Struct(fields)

    return type_from_abi_string(element_type_name)


def dispatch_parameter_types(abi_entry: ABI_JSON) -> list[tuple[str | None, Type]]:
    # TODO (#83): use proper validation
    abi_entry_typed = cast("Iterable[dict[str, Any]]", abi_entry)
    return [
        (entry["name"] if entry["name"] != "" else None, dispatch_type(entry))
        for entry in abi_entry_typed
    ]


def encode_args(*types_and_args: tuple[Type, Any]) -> bytes:
    if types_and_args:
        types, args = zip(*types_and_args, strict=True)
    else:
        types, args = (), ()
    return eth_abi.encode(
        [tp.canonical_form for tp in types],
        tuple(tp._normalize(arg) for tp, arg in zip(types, args, strict=True)),
    )


def decode_args(types: Iterable[Type], data: bytes) -> tuple[ABIType, ...]:
    canonical_types = [tp.canonical_form for tp in types]
    try:
        values = eth_abi.decode(canonical_types, data)
    except DecodingError as exc:
        # wrap possible `eth_abi` errors
        signature = "(" + ",".join(canonical_types) + ")"
        message = (
            f"Could not decode the return value with the expected signature {signature}: {exc}"
        )
        raise ABIDecodingError(message) from exc

    return tuple(tp._denormalize(value) for tp, value in zip(types, values, strict=True))
