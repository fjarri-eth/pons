import pytest

from pons import abi, Address
from pons._abi_types import type_from_abi_string, dispatch_type, dispatch_types


def test_uint():
    for val in [0, 255, 10]:
        assert abi.uint(8).normalize(val) == val
        assert abi.uint(8).denormalize(val) == val

    assert abi.uint(256).canonical_form == "uint256"
    assert abi.uint(8) == abi.uint(8)
    assert abi.uint(8) != abi.uint(16)

    for bit_size in [-1, 0, 255, 512]:
        with pytest.raises(ValueError, match=f"Incorrect `uint` bit size: {bit_size}"):
            abi.uint(bit_size)

    with pytest.raises(TypeError, match="`uint128` must correspond to an integer, got bool"):
        abi.uint(128).normalize(True)
    with pytest.raises(TypeError, match="`uint128` must correspond to an integer, got str"):
        abi.uint(128).normalize("abc")
    with pytest.raises(
        ValueError, match="`uint128` must correspond to a non-negative integer, got -1"
    ):
        abi.uint(128).normalize(-1)
    with pytest.raises(
        ValueError,
        match="`uint128` must correspond to an unsigned integer under 128 bits, got "
        + str(2**128),
    ):
        abi.uint(128).normalize(2**128)


def test_int():
    for val in [0, 127, -128, 10]:
        assert abi.int(8).normalize(val) == val
        assert abi.int(8).denormalize(val) == val

    assert abi.int(256).canonical_form == "int256"
    assert abi.int(8) == abi.int(8)
    assert abi.int(8) != abi.int(16)

    for bit_size in [-1, 0, 255, 512]:
        with pytest.raises(ValueError, match=f"Incorrect `int` bit size: {bit_size}"):
            abi.int(bit_size)

    with pytest.raises(TypeError, match="`int128` must correspond to an integer, got bool"):
        abi.int(128).normalize(True)
    with pytest.raises(TypeError, match="`int128` must correspond to an integer, got str"):
        abi.int(128).normalize("abc")
    with pytest.raises(
        ValueError,
        match="`int128` must correspond to a signed integer under 128 bits, got "
        + str(-(2**127) - 1),
    ):
        abi.int(128).normalize(-(2**127) - 1)
    with pytest.raises(
        ValueError,
        match="`int128` must correspond to a signed integer under 128 bits, got " + str(2**127),
    ):
        abi.int(128).normalize(2**127)


def test_bytes():
    assert abi.bytes(3).normalize(b"foo") == b"foo"
    assert abi.bytes(3).denormalize(b"foo") == b"foo"
    assert abi.bytes().normalize(b"foobar") == b"foobar"
    assert abi.bytes().denormalize(b"foobar") == b"foobar"

    assert abi.bytes(3).canonical_form == "bytes3"
    assert abi.bytes().canonical_form == "bytes"
    assert abi.bytes(8) == abi.bytes(8)
    assert abi.bytes(8) != abi.bytes(16)

    for size in [-1, 0, 33]:
        with pytest.raises(ValueError, match=f"Incorrect `bytes` size: {size}"):
            abi.bytes(size)

    with pytest.raises(TypeError, match="`bytes` must correspond to a bytestring, got str"):
        abi.bytes().normalize("foo")
    with pytest.raises(ValueError, match="Expected 4 bytes, got 3"):
        abi.bytes(4).normalize(b"foo")


def test_address():
    addr_bytes = b"\x01" * 20
    addr = Address(addr_bytes)

    assert abi.address.normalize(addr) == addr_bytes
    assert abi.address.denormalize(addr_bytes) == addr

    assert abi.address.canonical_form == "address"

    with pytest.raises(
        TypeError, match="`address` must correspond to an `Address`-type value, got str"
    ):
        abi.address.normalize("0x" + "01" * 20)


def test_string():
    assert abi.string.normalize("foo") == "foo"
    assert abi.string.denormalize("foo") == "foo"

    assert abi.string.canonical_form == "string"

    with pytest.raises(
        TypeError, match="`string` must correspond to a `str`-type value, got bytes"
    ):
        abi.string.normalize(b"foo")


def test_bool():
    assert abi.bool.normalize(True) == True
    assert abi.bool.denormalize(True) == True

    assert abi.bool.canonical_form == "bool"

    with pytest.raises(TypeError, match="`bool` must correspond to a `bool`-type value, got int"):
        abi.bool.normalize(1)


def test_array():
    assert abi.uint(8)[2].normalize([1, 2]) == [1, 2]
    assert abi.uint(8)[2].denormalize([1, 2]) == [1, 2]
    assert abi.uint(8)[...].normalize([1, 2, 3]) == [1, 2, 3]
    assert abi.uint(8)[...].denormalize([1, 2, 3]) == [1, 2, 3]

    assert abi.uint(8)[2].canonical_form == "uint8[2]"
    assert abi.uint(8)[...].canonical_form == "uint8[]"
    assert abi.uint(8)[2] == abi.uint(8)[2]
    assert abi.uint(8)[...] == abi.uint(8)[...]
    assert abi.uint(8)[...] != abi.uint(8)[2]

    with pytest.raises(TypeError, match="Expected an iterable, got int"):
        abi.uint(8)[1].normalize(1)
    with pytest.raises(ValueError, match="Expected 2 elements, got 3"):
        abi.uint(8)[2].normalize([1, 2, 3])


def test_struct():
    u8 = abi.uint(8)
    s1 = abi.struct(a=u8, b=abi.bool)

    s1_copy = abi.struct(a=u8, b=abi.bool)
    s2 = abi.struct(b=abi.bool, a=u8)

    assert s1.normalize(dict(b=True, a=1)) == [1, True]
    assert s1.normalize([1, True]) == [1, True]
    assert s1.denormalize([1, True]) == dict(a=1, b=True)

    assert s1.canonical_form == "(uint8,bool)"
    assert str(s1) == "(uint8 a, bool b)"
    assert s1 == s1_copy
    assert s1 != s2

    with pytest.raises(TypeError, match="Expected an iterable, got int"):
        s1.normalize(1)
    with pytest.raises(ValueError, match="Expected 2 elements, got 3"):
        s1.normalize([1, True, 2])
    with pytest.raises(ValueError, match=r"Expected fields \['a', 'b'\], got \['a', 'c'\]"):
        s1.normalize(dict(a=1, c=True))


def test_type_from_abi_string():
    assert type_from_abi_string("uint32") == abi.uint(32)
    assert type_from_abi_string("int64") == abi.int(64)
    assert type_from_abi_string("bytes11") == abi.bytes(11)
    assert type_from_abi_string("address") == abi.address
    assert type_from_abi_string("string") == abi.string
    assert type_from_abi_string("bool") == abi.bool

    with pytest.raises(ValueError, match="Unknown type: uintx"):
        type_from_abi_string("uintx")


def test_dispatch_type():
    assert dispatch_type(dict(type="uint8")) == abi.uint(8)
    assert dispatch_type(dict(type="uint8[2][]")) == abi.uint(8)[2][...]

    struct_array = dict(
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


def test_dispatch_types():
    entries = [
        dict(name="param2", type="uint8"),
        dict(name="param1", type="uint16[2]"),
    ]
    # Check that the order is preserved, too
    assert list(dispatch_types(entries).items()) == [
        ("param2", abi.uint(8)),
        ("param1", abi.uint(16)[2]),
    ]

    with pytest.raises(ValueError, match="All ABI entries must have distinct names"):
        dispatch_types([dict(name="", type="uint8"), dict(name="", type="uint16[2]")])


def test_making_arrays():
    assert abi.uint(8)[2].canonical_form == "uint8[2]"
    assert abi.uint(8)[...][3][...].canonical_form == "uint8[][3][]"

    with pytest.raises(TypeError, match="Invalid array size specifier type: float"):
        abi.uint(8)[1.0]


def test_normalization_roundtrip():

    struct = abi.struct(
        field1=abi.uint(8),
        field2=abi.uint(16)[2],
        field3=abi.address,
        field4=abi.struct(inner1=abi.bool, inner2=abi.string),
    )

    addr = Address(b"\x01" * 20)

    value = dict(field1=1, field2=[2, 3], field3=addr, field4=dict(inner2="abcd", inner1=True))

    expected_normalized = [1, [2, 3], bytes(addr), [True, "abcd"]]

    # normalize() loses info on struct field names
    assert struct.normalize(value) == expected_normalized

    # denormalize() should recover struct field names
    assert struct.denormalize(expected_normalized) == value
