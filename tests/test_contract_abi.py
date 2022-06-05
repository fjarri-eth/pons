from collections import namedtuple
import re

import pytest

from pons import (
    abi,
    Constructor,
    ReadMethod,
    WriteMethod,
    Fallback,
    Receive,
    ContractABI,
    Event,
    Error,
    Either,
    ABIDecodingError,
)
from pons._abi_types import keccak, encode_args
from pons._contract_abi import (
    Signature,
    EventSignature,
    PANIC_ERROR,
    LEGACY_ERROR,
    UnknownError,
)
from pons._entities import LogTopic


def test_signature_from_dict():
    sig = Signature(dict(a=abi.uint(8), b=abi.bool))
    assert sig.canonical_form == "(uint8,bool)"
    assert str(sig) == "(uint8 a, bool b)"
    assert sig.decode_into_tuple(sig.encode(1, True)) == (1, True)
    assert sig.decode_into_tuple(sig.encode(b=True, a=1)) == (1, True)
    assert sig.decode_into_dict(sig.encode(b=True, a=1)) == dict(b=True, a=1)


def test_signature_from_list():
    sig = Signature([abi.uint(8), abi.bool])
    assert str(sig) == "(uint8, bool)"
    assert sig.canonical_form == "(uint8,bool)"
    assert sig.decode_into_tuple(sig.encode(1, True)) == (1, True)
    assert sig.decode_into_dict(sig.encode(1, True)) == {"_0": 1, "_1": True}


def test_event_signature():
    sig = EventSignature(dict(a=abi.uint(8), b=abi.bool, c=abi.bytes(4)), {"a", "b"})
    assert str(sig) == "(uint8 indexed a, bool indexed b, bytes4 c)"
    assert sig.canonical_form == "(uint8,bool,bytes4)"
    assert sig.canonical_form_nonindexed == "(bytes4)"


def test_event_signature_encode():

    sig = EventSignature(dict(a=abi.uint(8), b=abi.bool, c=abi.bytes(4)), {"a", "b"})

    # All indexed parameters provided
    encoded = sig.encode_to_topics(1, True)
    assert encoded == ((abi.uint(8).encode(1),), (abi.bool.encode(True),))

    # One indexed parameter not provided
    encoded = sig.encode_to_topics(b=True)
    assert encoded == (None, (abi.bool.encode(True),))

    # An indexed parameter at the end not provided - the trailing Nones are trimmed
    encoded = sig.encode_to_topics(a=1)
    assert encoded == ((abi.uint(8).encode(1),),)

    # Using Either to encode several possible values for a parameter
    encoded = sig.encode_to_topics(a=Either(1, 2), b=True)
    assert encoded == (
        (abi.uint(8).encode(1), abi.uint(8).encode(2)),
        (abi.bool.encode(True),),
    )


def test_event_signature_decode():

    sig = EventSignature(dict(a=abi.uint(8), b=abi.bool, c=abi.bytes(4), d=abi.bytes()), {"a", "b"})

    decoded = sig.decode_log_entry(
        [abi.uint(8).encode(1), abi.bool.encode(True)],
        encode_args((abi.bytes(4), b"1234"), (abi.bytes(), b"bytestring")),
    )
    assert decoded == dict(a=1, b=True, c=b"1234", d=b"bytestring")

    message = re.escape(
        "The number of topics in the log entry (3) does not match "
        "the number of indexed fields in the event (2)"
    )
    with pytest.raises(ValueError, match=message):
        sig.decode_log_entry([b"1", b"2", b"3"], b"zzz")


def test_constructor_from_json():
    ctr = Constructor.from_json(
        dict(
            type="constructor",
            stateMutability="payable",
            inputs=[
                dict(type="uint8", name="a"),
                dict(type="bool", name="b"),
            ],
        )
    )
    assert ctr.payable
    assert ctr.inputs.canonical_form == "(uint8,bool)"
    assert str(ctr.inputs) == "(uint8 a, bool b)"


def test_constructor_init():
    ctr = Constructor(inputs=dict(a=abi.uint(8), b=abi.bool), payable=True)
    assert ctr.payable
    assert ctr.inputs.canonical_form == "(uint8,bool)"
    assert str(ctr.inputs) == "(uint8 a, bool b)"

    ctr_call = ctr(1, True)
    assert ctr_call.input_bytes == b"\x00" * 31 + b"\x01" + b"\x00" * 31 + b"\x01"


def test_constructor_errors():
    with pytest.raises(
        ValueError,
        match="Constructor object must be created from a JSON entry with type='constructor'",
    ):
        Constructor.from_json(dict(type="function"))

    with pytest.raises(ValueError, match="Constructor's JSON entry cannot have a `name`"):
        Constructor.from_json(dict(type="constructor", name="myConstructor"))

    with pytest.raises(
        ValueError, match="Constructor's JSON entry cannot have non-empty `outputs`"
    ):
        Constructor.from_json(dict(type="constructor", outputs=[dict(type="uint8", name="a")]))

    # This is fine though
    Constructor.from_json(dict(type="constructor", outputs=[], stateMutability="nonpayable"))

    with pytest.raises(
        ValueError,
        match="Constructor's JSON entry state mutability must be `nonpayable` or `payable`",
    ):
        Constructor.from_json(dict(type="constructor", stateMutability="view"))


def _check_read_method(read):
    assert read.name == "someMethod"
    assert read.inputs.canonical_form == "(uint8,bool)"
    assert str(read.inputs) == "(uint8 a, bool b)"
    assert read.outputs.canonical_form == "(uint8,bool)"

    encoded_bytes = b"\x00" * 31 + b"\x01" + b"\x00" * 31 + b"\x01"

    rcall = read(1, True)
    assert rcall.data_bytes == read.selector + encoded_bytes

    vals = read.decode_output(encoded_bytes)
    assert vals == (1, True)


def test_read_method_from_json_anonymous_outputs():
    read = ReadMethod.from_json(
        dict(
            type="function",
            name="someMethod",
            stateMutability="view",
            inputs=[
                dict(type="uint8", name="a"),
                dict(type="bool", name="b"),
            ],
            outputs=[
                dict(type="uint8", name=""),
                dict(type="bool", name=""),
            ],
        )
    )

    assert str(read.outputs) == "(uint8, bool)"
    _check_read_method(read)


def test_read_method_from_json_named_outputs():
    read = ReadMethod.from_json(
        dict(
            type="function",
            name="someMethod",
            stateMutability="view",
            inputs=[
                dict(type="uint8", name="a"),
                dict(type="bool", name="b"),
            ],
            outputs=[
                dict(type="uint8", name="c"),
                dict(type="bool", name="d"),
            ],
        )
    )

    assert str(read.outputs) == "(uint8 c, bool d)"
    _check_read_method(read)


def test_read_method_init():
    read = ReadMethod(
        name="someMethod",
        inputs=dict(a=abi.uint(8), b=abi.bool),
        outputs=dict(c=abi.uint(8), d=abi.bool),
    )

    assert str(read.outputs) == "(uint8 c, bool d)"
    _check_read_method(read)


def test_read_method_single_output():
    read = ReadMethod(
        name="someMethod", inputs=dict(a=abi.uint(8), b=abi.bool), outputs=abi.uint(8)
    )

    assert read.outputs.canonical_form == "(uint8)"
    assert str(read.outputs) == "(uint8)"

    encoded_bytes = b"\x00" * 31 + b"\x01"
    assert read.decode_output(encoded_bytes) == 1


def test_read_method_errors():
    with pytest.raises(
        ValueError, match="ReadMethod object must be created from a JSON entry with type='function'"
    ):
        ReadMethod.from_json(dict(type="constructor"))

    with pytest.raises(
        ValueError,
        match="Non-mutating method's JSON entry state mutability must be `pure` or `view`",
    ):
        ReadMethod.from_json(
            dict(
                type="function",
                name="someMethod",
                stateMutability="nonpayable",
                inputs=[dict(type="uint8", name="a")],
                outputs=[dict(type="uint8", name="")],
            )
        )


def _check_write_method(write):
    assert write.name == "someMethod"
    assert write.inputs.canonical_form == "(uint8,bool)"
    assert str(write.inputs) == "(uint8 a, bool b)"
    assert write.payable

    encoded_bytes = b"\x00" * 31 + b"\x01" + b"\x00" * 31 + b"\x01"

    wcall = write(1, True)
    assert wcall.data_bytes == write.selector + encoded_bytes


def test_write_method_from_json():
    write = WriteMethod.from_json(
        dict(
            type="function",
            name="someMethod",
            stateMutability="payable",
            inputs=[
                dict(type="uint8", name="a"),
                dict(type="bool", name="b"),
            ],
        )
    )

    _check_write_method(write)


def test_write_method_init():
    write = WriteMethod(name="someMethod", inputs=dict(a=abi.uint(8), b=abi.bool), payable=True)

    _check_write_method(write)


def test_write_method_errors():

    with pytest.raises(
        ValueError,
        match="WriteMethod object must be created from a JSON entry with type='function'",
    ):
        WriteMethod.from_json(dict(type="constructor"))

    with pytest.raises(
        ValueError, match="Mutating method's JSON entry cannot have non-empty `outputs`"
    ):
        WriteMethod.from_json(
            dict(
                type="function",
                name="someMethod",
                stateMutability="payable",
                inputs=[dict(type="uint8", name="a")],
                outputs=[dict(type="uint8", name="a")],
            )
        )

    # This is fine
    WriteMethod.from_json(
        dict(
            type="function",
            name="someMethod",
            stateMutability="payable",
            inputs=[dict(type="uint8", name="a")],
            outputs=[],
        )
    )

    with pytest.raises(
        ValueError,
        match="Mutating method's JSON entry state mutability must be `nonpayable` or `payable`",
    ):
        WriteMethod.from_json(
            dict(
                type="function",
                name="someMethod",
                stateMutability="view",
                inputs=[dict(type="uint8", name="a")],
            )
        )


def test_fallback():
    fallback = Fallback.from_json(dict(type="fallback", stateMutability="payable"))
    assert fallback.payable


def test_fallback_errors():
    with pytest.raises(
        ValueError, match="Fallback object must be created from a JSON entry with type='fallback'"
    ):
        Fallback.from_json(dict(type="function", stateMutability="payable"))
    with pytest.raises(
        ValueError,
        match="Fallback method's JSON entry state mutability must be `nonpayable` or `payable`",
    ):
        Fallback.from_json(dict(type="fallback", stateMutability="view"))


def test_receive():
    receive = Receive.from_json(dict(type="receive", stateMutability="payable"))
    assert receive.payable


def test_receive_errors():
    with pytest.raises(
        ValueError, match="Receive object must be created from a JSON entry with type='fallback'"
    ):
        Receive.from_json(dict(type="function", stateMutability="payable"))
    with pytest.raises(
        ValueError,
        match="Receive method's JSON entry state mutability must be `nonpayable` or `payable`",
    ):
        Receive.from_json(dict(type="receive", stateMutability="view"))


def test_contract_abi_json():
    constructor_abi = dict(
        type="constructor",
        stateMutability="payable",
        inputs=[
            dict(type="uint8", name="a"),
            dict(type="bool", name="b"),
        ],
    )

    read_abi = dict(
        type="function",
        name="readMethod",
        stateMutability="view",
        inputs=[
            dict(type="uint8", name="a"),
            dict(type="bool", name="b"),
        ],
        outputs=[
            dict(type="uint8", name=""),
            dict(type="bool", name=""),
        ],
    )

    write_abi = dict(
        type="function",
        name="writeMethod",
        stateMutability="payable",
        inputs=[
            dict(type="uint8", name="a"),
            dict(type="bool", name="b"),
        ],
    )

    event_abi = dict(
        type="event",
        name="Deposit",
        anonymous=True,
        inputs=[
            dict(indexed=True, internalType="address", name="from", type="address"),
            dict(indexed=True, internalType="bytes", name="foo", type="bytes"),
            dict(indexed=False, internalType="uint8", name="bar", type="uint8"),
        ],
    )

    error_abi = dict(
        type="error",
        name="CustomError",
        inputs=[
            dict(internalType="address", name="from", type="address"),
            dict(internalType="bytes", name="foo", type="bytes"),
            dict(internalType="uint8", name="bar", type="uint8"),
        ],
    )

    fallback_abi = dict(type="fallback", stateMutability="payable")
    receive_abi = dict(type="receive", stateMutability="payable")

    cabi = ContractABI.from_json(
        [constructor_abi, read_abi, write_abi, fallback_abi, receive_abi, event_abi, error_abi]
    )
    assert str(cabi) == (
        "{\n"
        "    constructor(uint8 a, bool b) payable\n"
        "    fallback() payable\n"
        "    receive() payable\n"
        "    function readMethod(uint8 a, bool b) returns (uint8, bool)\n"
        "    function writeMethod(uint8 a, bool b) payable\n"
        "    event Deposit(address indexed from, bytes indexed foo, uint8 bar) anonymous\n"
        "    error CustomError(address from, bytes foo, uint8 bar)\n"
        "}"
    )

    assert isinstance(cabi.constructor, Constructor)
    assert isinstance(cabi.fallback, Fallback)
    assert isinstance(cabi.receive, Receive)
    assert isinstance(cabi.read.readMethod, ReadMethod)
    assert isinstance(cabi.write.writeMethod, WriteMethod)
    assert isinstance(cabi.event.Deposit, Event)
    assert isinstance(cabi.error.CustomError, Error)


def test_contract_abi_init():
    cabi = ContractABI(
        constructor=Constructor(inputs=dict(a=abi.uint(8), b=abi.bool), payable=True),
        write=[
            WriteMethod(name="writeMethod", inputs=dict(a=abi.uint(8), b=abi.bool), payable=True)
        ],
        read=[
            ReadMethod(
                name="readMethod",
                inputs=dict(a=abi.uint(8), b=abi.bool),
                outputs=[abi.uint(8), abi.bool],
            )
        ],
        events=[
            Event(
                name="Deposit",
                fields=dict(from_=abi.address, foo=abi.bytes(), bar=abi.uint(8)),
                indexed={"from_", "foo"},
                anonymous=True,
            )
        ],
        errors=[
            Error(
                "CustomError",
                dict(from_=abi.address, foo=abi.bytes(), bar=abi.uint(8)),
            )
        ],
        fallback=Fallback(payable=True),
        receive=Receive(payable=True),
    )

    assert str(cabi) == (
        "{\n"
        "    constructor(uint8 a, bool b) payable\n"
        "    fallback() payable\n"
        "    receive() payable\n"
        "    function readMethod(uint8 a, bool b) returns (uint8, bool)\n"
        "    function writeMethod(uint8 a, bool b) payable\n"
        "    event Deposit(address indexed from_, bytes indexed foo, uint8 bar) anonymous\n"
        "    error CustomError(address from_, bytes foo, uint8 bar)\n"
        "}"
    )

    assert isinstance(cabi.constructor, Constructor)
    assert isinstance(cabi.fallback, Fallback)
    assert isinstance(cabi.receive, Receive)
    assert isinstance(cabi.read.readMethod, ReadMethod)
    assert isinstance(cabi.write.writeMethod, WriteMethod)


def test_no_constructor():
    cabi = ContractABI()
    assert isinstance(cabi.constructor, Constructor)
    assert cabi.constructor.inputs.canonical_form == "()"


def test_contract_abi_errors():
    constructor_abi = dict(type="constructor", stateMutability="payable", inputs=[])
    with pytest.raises(
        ValueError, match="JSON ABI contains more than one constructor declarations"
    ):
        abi = ContractABI.from_json([constructor_abi, constructor_abi])

    write_abi = dict(type="function", name="someMethod", stateMutability="payable", inputs=[])
    with pytest.raises(
        ValueError, match="JSON ABI contains more than one declarations of `someMethod`"
    ):
        abi = ContractABI.from_json([write_abi, write_abi])

    fallback_abi = dict(type="fallback", stateMutability="payable")
    with pytest.raises(ValueError, match="JSON ABI contains more than one fallback declarations"):
        abi = ContractABI.from_json([fallback_abi, fallback_abi])

    receive_abi = dict(type="receive", stateMutability="payable")
    with pytest.raises(
        ValueError, match="JSON ABI contains more than one receive method declarations"
    ):
        abi = ContractABI.from_json([receive_abi, receive_abi])

    event_abi = dict(type="event", name="Foo", inputs=[], anonymous=False)
    with pytest.raises(ValueError, match="JSON ABI contains more than one declarations of `Foo`"):
        abi = ContractABI.from_json([event_abi, event_abi])

    error_abi = dict(type="error", name="Foo", inputs=[])
    with pytest.raises(ValueError, match="JSON ABI contains more than one declarations of `Foo`"):
        abi = ContractABI.from_json([error_abi, error_abi])

    with pytest.raises(ValueError, match="Unknown ABI entry type: foobar"):
        abi = ContractABI.from_json([dict(type="foobar")])


def test_event_from_json():
    event = Event.from_json(
        dict(
            anonymous=True,
            inputs=[
                dict(indexed=True, internalType="address", name="from", type="address"),
                dict(indexed=True, internalType="bytes", name="foo", type="bytes"),
                dict(indexed=False, internalType="uint8", name="bar", type="uint8"),
            ],
            name="Foo",
            type="event",
        )
    )
    assert event.anonymous
    assert event.name == "Foo"
    assert event.indexed == {"from", "foo"}
    assert str(event.fields) == "(address indexed from, bytes indexed foo, uint8 bar)"


def test_event_init():
    event = Event(
        "Foo",
        dict(from_=abi.address, foo=abi.bytes(), bar=abi.uint(8)),
        indexed={"from_", "foo"},
        anonymous=True,
    )
    assert event.anonymous
    assert event.name == "Foo"
    assert event.indexed == {"from_", "foo"}
    assert str(event.fields) == "(address indexed from_, bytes indexed foo, uint8 bar)"


def test_event_encode():

    event = Event("Foo", dict(a=abi.bool, b=abi.uint(8), c=abi.bytes(4)), {"a", "b"})
    event_filter = event(b=Either(1, 2))
    assert event_filter.topics == (
        (LogTopic(keccak(event.name.encode() + event.fields.canonical_form.encode())),),
        None,
        (LogTopic(abi.uint(8).encode(1)), LogTopic(abi.uint(8).encode(2))),
    )

    # Anonymous event filter does not include the selector
    event = Event(
        "Foo", dict(a=abi.bool, b=abi.uint(8), c=abi.bytes(4)), {"a", "b"}, anonymous=True
    )
    event_filter = event(b=Either(1, 2))
    assert event_filter.topics == (
        None,
        (LogTopic(abi.uint(8).encode(1)), LogTopic(abi.uint(8).encode(2))),
    )


def test_event_decode():

    # We only need a couple of fields
    fake_log_entry = namedtuple("fake_log_entry", ["topics", "data"])

    event = Event("Foo", dict(a=abi.bool, b=abi.uint(8), c=abi.bytes(4), d=abi.bytes()), {"a", "b"})

    decoded = event.decode_log_entry(
        fake_log_entry(
            [
                LogTopic(keccak(event.name.encode() + event.fields.canonical_form.encode())),
                LogTopic(abi.bool.encode(True)),
                LogTopic(abi.uint(8).encode(2)),
            ],
            encode_args((abi.bytes(4), b"1234"), (abi.bytes(), b"bytestring")),
        )
    )
    assert decoded == dict(a=True, b=2, c=b"1234", d=b"bytestring")

    # Wrong selector
    with pytest.raises(ValueError, match="This log entry belongs to a different event"):
        decoded = event.decode_log_entry(
            fake_log_entry(
                [
                    LogTopic(keccak(b"NotFoo" + event.fields.canonical_form.encode())),
                    LogTopic(abi.bool.encode(True)),
                    LogTopic(abi.uint(8).encode(2)),
                ],
                encode_args((abi.bytes(4), b"1234"), (abi.bytes(), b"bytestring")),
            )
        )

    # Anonymous event

    event = Event(
        "Foo",
        dict(a=abi.bool, b=abi.uint(8), c=abi.bytes(4), d=abi.bytes()),
        {"a", "b"},
        anonymous=True,
    )

    decoded = event.decode_log_entry(
        fake_log_entry(
            [LogTopic(abi.bool.encode(True)), LogTopic(abi.uint(8).encode(2))],
            encode_args((abi.bytes(4), b"1234"), (abi.bytes(), b"bytestring")),
        )
    )
    assert decoded == dict(a=True, b=2, c=b"1234", d=b"bytestring")


def test_event_errors():
    with pytest.raises(
        ValueError,
        match="Event object must be created from a JSON entry with type='event'",
    ):
        Event.from_json(dict(type="constructor"))

    uint8 = abi.uint(8)

    with pytest.raises(ValueError, match="Anonymous events can have at most 4 indexed fields"):
        Event(
            "Foo",
            dict(a=uint8, b=uint8, c=uint8, d=uint8, e=uint8),
            indexed={"a", "b", "c", "d", "e"},
            anonymous=True,
        )

    # This works
    Event(
        "Foo",
        dict(a=uint8, b=uint8, c=uint8, d=uint8, e=uint8),
        indexed={"a", "b", "c", "d"},
        anonymous=True,
    )

    with pytest.raises(ValueError, match="Non-anonymous events can have at most 3 indexed fields"):
        Event(
            "Foo", dict(a=uint8, b=uint8, c=uint8, d=uint8, e=uint8), indexed={"a", "b", "c", "d"}
        )

    # This works
    Event("Foo", dict(a=uint8, b=uint8, c=uint8, d=uint8, e=uint8), indexed={"a", "b", "c"})


def test_error_from_json():
    error = Error.from_json(
        dict(
            inputs=[
                dict(internalType="address", name="from", type="address"),
                dict(internalType="bytes", name="foo", type="bytes"),
                dict(internalType="uint8", name="bar", type="uint8"),
            ],
            name="Foo",
            type="error",
        )
    )
    assert error.name == "Foo"
    assert str(error.fields) == "(address from, bytes foo, uint8 bar)"

    with pytest.raises(
        ValueError,
        match="Error object must be created from a JSON entry with type='error'",
    ):
        Error.from_json(dict(type="constructor"))


def test_error_init():
    error = Error(
        "Foo",
        dict(from_=abi.address, foo=abi.bytes(), bar=abi.uint(8)),
    )
    assert error.name == "Foo"
    assert str(error.fields) == "(address from_, bytes foo, uint8 bar)"


def test_error_decode():
    error = Error(
        "Foo",
        dict(foo=abi.bytes(), bar=abi.uint(8)),
    )

    encoded_bytes = encode_args((abi.bytes(), b"12345"), (abi.uint(8), 9))
    decoded = error.decode_fields(encoded_bytes)
    assert decoded == dict(foo=b"12345", bar=9)


def test_resolve_error():
    error1 = Error("Error1", dict(foo=abi.bytes(), bar=abi.uint(8)))
    error2 = Error("Error2", dict(foo=abi.bool, bar=abi.string))
    contract_abi = ContractABI(errors=[error1, error2])

    # Decode custom error
    error_data = error1.selector + error1.fields.encode(b"12345", 9)
    error, decoded = contract_abi.resolve_error(error_data)
    assert error is error1
    assert decoded == dict(foo=b"12345", bar=9)

    # Decode a panic (the description is added automatically to the ABI)
    error_data = PANIC_ERROR.selector + PANIC_ERROR.fields.encode(9)
    error, decoded = contract_abi.resolve_error(error_data)
    assert error is PANIC_ERROR
    assert decoded == dict(code=9)

    # Decode a legacy error (the description is added automatically to the ABI)
    error_data = LEGACY_ERROR.selector + LEGACY_ERROR.fields.encode("error message")
    error, decoded = contract_abi.resolve_error(error_data)
    assert error is LEGACY_ERROR
    assert decoded == dict(message="error message")

    with pytest.raises(ValueError, match="Error data too short to contain a selector"):
        contract_abi.resolve_error(b"123")

    bad_selector = b"1234"
    with pytest.raises(
        UnknownError, match=f"Could not find an error with selector {bad_selector.hex()} in the ABI"
    ):
        contract_abi.resolve_error(bad_selector + error1.fields.encode(b"12345", 9))
