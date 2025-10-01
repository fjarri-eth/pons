import os
from typing import Any

import pytest
from ethereum_rpc import Address, keccak

from pons import abi
from pons._abi_types import (
    ABI_JSON,
    ABIDecodingError,
    ABIType,
    Type,
    decode_args,
    dispatch_type,
    dispatch_types,
    encode_args,
    type_from_abi_string,
)


def test_uint() -> None:
    for val in [0, 255, 10]:
        assert abi.uint(8)._normalize(val) == val
        assert abi.uint(8)._denormalize(val) == val

    assert abi.uint(256).canonical_form == "uint256"
    assert abi.uint(8) == abi.uint(8)
    assert abi.uint(8) != abi.uint(16)

    assert hash(abi.uint(8)) == hash(abi.uint(8))
    assert hash(abi.uint(8)) != hash(abi.uint(256))

    for bit_size in [-1, 0, 255, 512]:
        with pytest.raises(ValueError, match=f"Incorrect `uint` bit size: {bit_size}"):
            abi.uint(bit_size)

    with pytest.raises(TypeError, match="`uint128` must correspond to an integer, got bool"):
        abi.uint(128)._normalize(True)
    with pytest.raises(TypeError, match="`uint128` must correspond to an integer, got str"):
        abi.uint(128)._normalize("abc")
    with pytest.raises(
        ValueError, match="`uint128` must correspond to a non-negative integer, got -1"
    ):
        abi.uint(128)._normalize(-1)
    with pytest.raises(
        ValueError,
        match="`uint128` must correspond to an unsigned integer under 128 bits, got " + str(2**128),
    ):
        abi.uint(128)._normalize(2**128)


def test_int() -> None:
    for val in [0, 127, -128, 10]:
        assert abi.int(8)._normalize(val) == val
        assert abi.int(8)._denormalize(val) == val

    assert abi.int(256).canonical_form == "int256"
    assert abi.int(8) == abi.int(8)
    assert abi.int(8) != abi.int(16)

    assert hash(abi.int(8)) == hash(abi.int(8))
    assert hash(abi.int(8)) != hash(abi.int(256))

    for bit_size in [-1, 0, 255, 512]:
        with pytest.raises(ValueError, match=f"Incorrect `int` bit size: {bit_size}"):
            abi.int(bit_size)

    with pytest.raises(TypeError, match="`int128` must correspond to an integer, got bool"):
        abi.int(128)._normalize(True)
    with pytest.raises(TypeError, match="`int128` must correspond to an integer, got str"):
        abi.int(128)._normalize("abc")
    with pytest.raises(
        ValueError,
        match="`int128` must correspond to a signed integer under 128 bits, got "
        + str(-(2**127) - 1),
    ):
        abi.int(128)._normalize(-(2**127) - 1)
    with pytest.raises(
        ValueError,
        match="`int128` must correspond to a signed integer under 128 bits, got " + str(2**127),
    ):
        abi.int(128)._normalize(2**127)


def test_bytes() -> None:
    assert abi.bytes(3)._normalize(b"foo") == b"foo"
    assert abi.bytes(3)._denormalize(b"foo") == b"foo"
    assert abi.bytes()._normalize(b"foobar") == b"foobar"
    assert abi.bytes()._denormalize(b"foobar") == b"foobar"

    assert abi.bytes(3).canonical_form == "bytes3"
    assert abi.bytes().canonical_form == "bytes"
    assert abi.bytes(8) == abi.bytes(8)
    assert abi.bytes(8) != abi.bytes(16)

    assert hash(abi.bytes(8)) == hash(abi.bytes(8))
    assert hash(abi.bytes(8)) != hash(abi.bytes(3))

    for size in [-1, 0, 33]:
        with pytest.raises(ValueError, match=f"Incorrect `bytes` size: {size}"):
            abi.bytes(size)

    with pytest.raises(TypeError, match="`bytes` must correspond to a bytestring, got str"):
        abi.bytes()._normalize("foo")
    with pytest.raises(ValueError, match="Expected 4 bytes, got 3"):
        abi.bytes(4)._normalize(b"foo")


def test_address() -> None:
    addr_bytes = os.urandom(20)
    addr = Address(addr_bytes)

    assert abi.address._normalize(addr) == addr.checksum
    assert abi.address._denormalize(addr.checksum) == addr

    assert abi.address.canonical_form == "address"

    assert hash(abi.address) == hash(abi.address)

    with pytest.raises(
        TypeError, match="`address` must correspond to an `Address`-type value, got str"
    ):
        abi.address._normalize("0x" + "01" * 20)

    with pytest.raises(TypeError, match="Expected a string to convert to `Address`, got bytes"):
        abi.address._denormalize(addr_bytes)


def test_string() -> None:
    assert abi.string._normalize("foo") == "foo"
    assert abi.string._denormalize("foo") == "foo"

    assert abi.string.canonical_form == "string"

    assert hash(abi.string) == hash(abi.string)

    with pytest.raises(
        TypeError, match="`string` must correspond to a `str`-type value, got bytes"
    ):
        abi.string._normalize(b"foo")


def test_bool() -> None:
    assert abi.bool._normalize(True) is True
    assert abi.bool._denormalize(True) is True

    assert abi.bool.canonical_form == "bool"

    assert hash(abi.bool) == hash(abi.bool)

    with pytest.raises(TypeError, match="`bool` must correspond to a `bool`-type value, got int"):
        abi.bool._normalize(1)


def test_array() -> None:
    assert abi.uint(8)[2]._normalize([1, 2]) == [1, 2]
    assert abi.uint(8)[2]._denormalize([1, 2]) == [1, 2]
    assert abi.uint(8)[...]._normalize([1, 2, 3]) == [1, 2, 3]
    assert abi.uint(8)[...]._denormalize([1, 2, 3]) == [1, 2, 3]

    assert abi.uint(8)[2].canonical_form == "uint8[2]"
    assert abi.uint(8)[...].canonical_form == "uint8[]"
    assert abi.uint(8)[2] == abi.uint(8)[2]
    assert abi.uint(8)[...] == abi.uint(8)[...]
    assert abi.uint(8)[...] != abi.uint(8)[2]

    assert hash(abi.uint(8)[2]) == hash(abi.uint(8)[2])
    assert hash(abi.uint(8)[...]) == hash(abi.uint(8)[...])
    assert hash(abi.uint(8)[2]) != hash(abi.uint(8)[3])
    assert hash(abi.uint(8)[2]) != hash(abi.uint(8)[...])

    with pytest.raises(TypeError, match="Expected an iterable, got int"):
        abi.uint(8)[1]._normalize(1)
    with pytest.raises(ValueError, match="Expected 2 elements, got 3"):
        abi.uint(8)[2]._normalize([1, 2, 3])


def test_struct() -> None:
    u8 = abi.uint(8)
    s1 = abi.struct(a=u8, b=abi.bool)

    s1_copy = abi.struct(a=u8, b=abi.bool)
    s2 = abi.struct(b=abi.bool, a=u8)

    assert s1._normalize(dict(b=True, a=1)) == [1, True]
    assert s1._normalize([1, True]) == [1, True]
    assert s1._denormalize([1, True]) == dict(a=1, b=True)

    assert s1.canonical_form == "(uint8,bool)"
    assert str(s1) == "(uint8 a, bool b)"
    assert s1 == s1_copy
    assert s1 != s2

    assert hash(s1) == hash(s1_copy)
    assert hash(s1) != hash(s2)

    with pytest.raises(TypeError, match="Expected an iterable, got int"):
        s1._normalize(1)
    with pytest.raises(ValueError, match="Expected 2 elements, got 3"):
        s1._normalize([1, True, 2])
    with pytest.raises(ValueError, match=r"Expected fields \['a', 'b'\], got \['a', 'c'\]"):
        s1._normalize(dict(a=1, c=True))


def test_type_from_abi_string() -> None:
    assert type_from_abi_string("uint32") == abi.uint(32)
    assert type_from_abi_string("int64") == abi.int(64)
    assert type_from_abi_string("bytes11") == abi.bytes(11)
    assert type_from_abi_string("address") == abi.address
    assert type_from_abi_string("string") == abi.string
    assert type_from_abi_string("bool") == abi.bool

    with pytest.raises(ValueError, match="Unknown type: uintx"):
        type_from_abi_string("uintx")


def test_dispatch_type() -> None:
    assert dispatch_type(dict(type="uint8")) == abi.uint(8)
    assert dispatch_type(dict(type="uint8[2][]")) == abi.uint(8)[2][...]

    struct_array: ABI_JSON = dict(
        type="tuple[2]",
        components=[
            dict(name="field1", type="bool"),
            dict(name="field2", type="address"),
        ],
    )
    assert dispatch_type(struct_array) == abi.struct(field1=abi.bool, field2=abi.address)[2]

    with pytest.raises(ValueError, match=r"Incorrect type format: uint8\(2\)"):
        dispatch_type(dict(type="uint8(2)"))
    with pytest.raises(ValueError, match=r"Incorrect type format: uint8\(2\)"):
        dispatch_type(dict(type="uint8(2)[3]"))


def test_dispatch_types() -> None:
    entries = [
        dict(name="param2", type="uint8"),
        dict(name="param1", type="uint16[2]"),
    ]

    assert dispatch_types(entries) == dict(param2=abi.uint(8), param1=abi.uint(16)[2])

    # Check that the order is preserved, too
    typed_entries = dispatch_types(entries)
    assert isinstance(typed_entries, dict)
    assert list(typed_entries.items()) == [
        ("param2", abi.uint(8)),
        ("param1", abi.uint(16)[2]),
    ]

    # Note that if all the names are empty, it is treated as a list of positional arguments
    assert dispatch_types([dict(name="", type="uint8"), dict(name="", type="uint16[2]")]) == [
        abi.uint(8),
        abi.uint(16)[2],
    ]

    # For an empty argument list we choose to resolve it as an empty dictionary, for certainty.
    assert dispatch_types([]) == {}

    with pytest.raises(ValueError, match="Arguments must be either all named or all unnamed"):
        dispatch_types([dict(name="foo", type="uint8"), dict(name="", type="uint16[2]")])

    with pytest.raises(ValueError, match="All ABI entries must have distinct names"):
        dispatch_types([dict(name="foo", type="uint8"), dict(name="foo", type="uint16[2]")])


def test_making_arrays() -> None:
    assert abi.uint(8)[2].canonical_form == "uint8[2]"
    assert abi.uint(8)[...][3][...].canonical_form == "uint8[][3][]"

    with pytest.raises(TypeError, match="Invalid array size specifier type: float"):
        abi.uint(8)[1.0]  # type: ignore[index]


def test_normalization_roundtrip() -> None:
    struct = abi.struct(
        field1=abi.uint(8),
        field2=abi.uint(16)[2],
        field3=abi.address,
        field4=abi.struct(inner1=abi.bool, inner2=abi.string),
    )

    addr = Address(b"\x01" * 20)

    value = dict(field1=1, field2=[2, 3], field3=addr, field4=dict(inner2="abcd", inner1=True))

    expected_normalized: ABIType = [1, [2, 3], addr.checksum, [True, "abcd"]]

    # normalize() loses info on struct field names
    assert struct._normalize(value) == expected_normalized

    # denormalize() should recover struct field names
    assert struct._denormalize(expected_normalized) == value


def check_topic_encode_decode(
    tp: Type, val: Any, encoded_val: bytes, *, can_be_decoded: bool = True
) -> None:
    assert tp.encode_to_topic(val) == encoded_val
    if can_be_decoded:
        assert tp.decode_from_topic(encoded_val) == val
    else:
        assert tp.decode_from_topic(encoded_val) is None


def test_encode_to_topic() -> None:
    # Simple types

    check_topic_encode_decode(
        abi.uint(32), 0x12345678, b"\x00" * 28 + (0x12345678).to_bytes(4, "big")
    )
    check_topic_encode_decode(
        abi.int(32), 0x12345678, b"\x00" * 28 + (0x12345678).to_bytes(4, "big")
    )
    check_topic_encode_decode(abi.bool, True, b"\x00" * 31 + b"\x01")

    address = Address(os.urandom(20))
    check_topic_encode_decode(abi.address, address, b"\x00" * 12 + bytes(address))

    # Corner cases
    check_topic_encode_decode(abi.bytes(), b"", keccak(b""), can_be_decoded=False)
    eth_word = os.urandom(32)
    check_topic_encode_decode(abi.bytes(32), eth_word, eth_word)
    check_topic_encode_decode(abi.bytes(), eth_word, keccak(eth_word), can_be_decoded=False)

    small_bytes = os.urandom(5)
    check_topic_encode_decode(abi.bytes(5), small_bytes, small_bytes + b"\x00" * 27)
    check_topic_encode_decode(abi.bytes(), small_bytes, keccak(small_bytes), can_be_decoded=False)

    big_bytes = os.urandom(33)
    check_topic_encode_decode(abi.bytes(), big_bytes, keccak(big_bytes), can_be_decoded=False)

    string = "\u1234abcd"  # using Unicode here to check that encoding is happening
    check_topic_encode_decode(abi.string, string, keccak(string.encode()), can_be_decoded=False)

    # Arrays

    tp = abi.bytes()[2]
    small_bytes = os.urandom(5)
    big_bytes = os.urandom(33)
    val: Any = [small_bytes, big_bytes]
    # Values in the array are padded to multiples of 32 bytes
    encoded_val = keccak(small_bytes + b"\x00" * 27 + big_bytes + b"\x00" * 31)
    check_topic_encode_decode(tp, val, encoded_val, can_be_decoded=False)

    # Structs

    struct_tp = abi.struct(
        field1=abi.bytes()[2],
        field2=abi.bool,
        field3=abi.struct(inner1=abi.bytes(5), inner2=abi.string),
    )
    small_bytes = os.urandom(5)
    big_bytes = os.urandom(33)
    string = "abcdefghijklmnopqrstuvwxyz0123456789"
    val = [[small_bytes, big_bytes], True, [small_bytes, string]]
    # Values in the struct and nested arrays/structs are padded to multiples of 32 bytes
    encoded_val = keccak(
        (small_bytes + b"\x00" * 27)
        + (big_bytes + b"\x00" * 31)
        + (b"\x00" * 31 + b"\x01")
        + (small_bytes + b"\x00" * 27)
        + (string.encode() + b"\x00" * 28)
    )
    check_topic_encode_decode(struct_tp, val, encoded_val, can_be_decoded=False)


def test_encode_decode_args() -> None:
    args = ("some string", b"bytestring", 1234)
    types = [abi.string, abi.bytes(), abi.uint(256)]
    encoded = encode_args(*zip(types, args, strict=True))
    assert decode_args(types, encoded) == args

    # empty types/args list
    assert encode_args() == b""


def test_decoding_error() -> None:
    types = [abi.uint(256), abi.uint(256)]
    encoded_bytes = b"\x00" * 31 + b"\x01"  # Only one uint256

    expected_message = (
        r"Could not decode the return value with the expected signature \(uint256,uint256\): "
        r"Tried to read 32 bytes, only got 0 bytes"
    )

    with pytest.raises(ABIDecodingError, match=expected_message):
        decode_args(types, encoded_bytes)
