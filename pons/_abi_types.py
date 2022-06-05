from abc import ABC, abstractmethod
from functools import cached_property
import re
from typing import Optional, Any, Union, Iterable, Mapping, Dict, Tuple

from eth_abi.exceptions import DecodingError
from eth_abi import encode_single, decode_single
from eth_utils import keccak

from ._entities import Address


class ABIDecodingError(Exception):
    """
    Raised on an error when decoding a value in an Eth ABI encoded bytestring.
    """


def decode_abi(signature: str, data: bytes) -> Tuple[Any, ...]:
    try:
        return decode_single(signature, data)
    except DecodingError as exc:
        # wrap possible `eth_abi` errors
        message = (
            f"Could not decode the return value "
            f"with the expected signature {signature}: {str(exc)}"
        )
        raise ABIDecodingError(message) from exc


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
    def _normalize(self, val) -> Any:
        """
        Checks and possibly normalizes the value making it ready to be passed
        to ``encode()`` for encoding.
        """
        ...

    @abstractmethod
    def _denormalize(self, val) -> Any:
        """
        Checks the result of ``decode()``
        and wraps it in a specific type, if applicable.
        """
        ...

    def encode(self, val) -> bytes:
        """
        Encodes the given value in the contract ABI format.
        """
        return encode_single(self.canonical_form, val)

    def decode(self, val: bytes) -> Any:
        """
        Encodes the given value in the contract ABI format.
        """
        return decode_abi(self.canonical_form, val)

    def encode_to_topic(self, val) -> bytes:
        """
        Encodes the given value as an event topic.
        """
        # EVM uses a simpler encoding scheme for encoding values into event topics
        # because objects of reference types are just hashed,
        # and there is no need to unpack them later
        # (basically, all values are just concatenated without any lentgh labels).
        # Therefore we have to provide these methods
        # and cannot just use the functions from ``eth_abi``.

        # Before doing anything, normalize the value,
        # this will check that ensure the constituent values are actually valid.
        return self._encode_to_topic_outer(self._normalize(val))

    def _encode_to_topic_outer(self, val) -> bytes:
        """
        Encodes a value of the outer indexed type.
        """
        # By default it's just the encoding of the value type.
        # May be overridden.
        return self.encode(val)

    def _encode_to_topic_inner(self, val) -> bytes:
        """
        Encodes a value contained within an indexed array or struct.
        """
        # By default it's just the encoding of the value type.
        # May be overridden.
        return self.encode(val)

    def decode_from_topic(self, val: bytes) -> Any:
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
        return self._denormalize(self.decode(val))

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

    def _normalize(self, val):
        self._check_val(val)
        return int(val)

    def _denormalize(self, val):
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

    def _normalize(self, val):
        self._check_val(val)
        return val

    def _denormalize(self, val):
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

    def _normalize(self, val):
        self._check_val(val)
        return val

    def _denormalize(self, val):
        self._check_val(val)
        return val

    def _encode_to_topic_outer(self, val):
        if self._size is None:
            # Dynamic `bytes` is a reference type and is therefore hashed.
            return keccak(val)
        else:
            # Sized `bytes` is a value type, falls back to the base implementation.
            return super()._encode_to_topic_outer(val)

    def _encode_to_topic_inner(self, val):
        if self._size is None:
            # Dynamic `bytes` is padded to a multiple of 32 bytes.
            padding_len = (32 - len(val)) % 32
            return val + b"\x00" * padding_len
        else:
            # Sized `bytes` is a value type, falls back to the base implementation.
            return super()._encode_to_topic_inner(val)

    def decode_from_topic(self, val):
        if self._size is None:
            # Cannot recover a hashed value.
            return None
        else:
            return super().decode_from_topic(val)

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

    def _normalize(self, val):
        if not isinstance(val, Address):
            raise TypeError(
                f"`address` must correspond to an `Address`-type value, "
                f"got {type(val).__name__}"
            )
        return bytes(val)

    def _denormalize(self, val):
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

    def _normalize(self, val):
        self._check_val(val)
        return val

    def _denormalize(self, val):
        self._check_val(val)
        return val

    def _encode_to_topic_outer(self, val):
        # `string` is encoded and treated as dynamic `bytes`
        return Bytes()._encode_to_topic_outer(val.encode())

    def _encode_to_topic_inner(self, val):
        # `string` is encoded and treated as dynamic `bytes`
        return Bytes()._encode_to_topic_inner(val.encode())

    def decode_from_topic(self, val):
        # Dynamic `bytes` is hashed, so the value cannot be recovered.
        return None

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

    def _normalize(self, val):
        self._check_val(val)
        return val

    def _denormalize(self, val):
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

    def _normalize(self, val):
        self._check_val(val)
        return [self._element_type._normalize(item) for item in val]

    def _denormalize(self, val):
        self._check_val(val)
        return [self._element_type._denormalize(item) for item in val]

    def _encode_to_topic_outer(self, val):
        return keccak(self._encode_to_topic_inner(val))

    def _encode_to_topic_inner(self, val):
        return b"".join(self._element_type._encode_to_topic_inner(elem) for elem in val)

    def decode_from_topic(self, val):
        return None

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

    def _normalize(self, val):
        if isinstance(val, Mapping):
            if val.keys() != self._fields.keys():
                raise ValueError(
                    f"Expected fields {list(self._fields.keys())}, got {list(val.keys())}"
                )
            return [tp._normalize(val[name]) for name, tp in self._fields.items()]
        else:
            self._check_val(val)
            return [tp._normalize(item) for item, tp in zip(val, self._fields.values())]

    def _denormalize(self, val):
        self._check_val(val)
        return {name: tp._denormalize(item) for item, (name, tp) in zip(val, self._fields.items())}

    def _encode_to_topic_outer(self, val):
        return keccak(self._encode_to_topic_inner(val))

    def _encode_to_topic_inner(self, val):
        return b"".join(
            tp._encode_to_topic_inner(elem) for elem, tp in zip(val, self._fields.values())
        )

    def decode_from_topic(self, val):
        return None

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
    if array_size is not None:
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


def canonical_signature(types: Iterable[Type]) -> str:
    return "(" + ",".join(tp.canonical_form for tp in types) + ")"


def encode_args(*types_and_args: Tuple[Type, Any]) -> bytes:
    if types_and_args:
        types, args = zip(*types_and_args)
    else:
        types, args = (), ()
    return encode_single(
        canonical_signature(types), tuple(tp._normalize(arg) for tp, arg in zip(types, args))
    )


def decode_args(types: Iterable[Type], data: bytes) -> Tuple[Any, ...]:
    values = decode_abi(canonical_signature(types), data)
    return tuple(tp._denormalize(value) for tp, value in zip(types, values))
