import re
from copy import deepcopy
from pathlib import Path

import pytest
import solcx
from ethereum_rpc import Address, BlockHash, LogEntry, LogTopic, TxHash, keccak

from pons import (
    ABI_JSON,
    Constructor,
    ContractABI,
    Either,
    Error,
    Event,
    EventFields,
    Fallback,
    Fields,
    FieldValues,
    Method,
    MultiMethod,
    Mutability,
    Receive,
    abi,
)
from pons._abi_types import encode_args
from pons._contract_abi import LEGACY_ERROR, PANIC_ERROR, UnknownError


def test_field_values() -> None:
    vals = FieldValues([("a", 1), ("b", 2)])
    assert vals.as_dict == dict(a=1, b=2)
    assert vals.as_tuple == (1, 2)
    assert vals["b"] == 2
    assert vals.b == 2
    assert repr(vals) == "FieldValues([('a', 1), ('b', 2)])"

    with pytest.raises(ValueError, match="The values cannot have repeating names"):
        FieldValues([("a", 1), ("a", 2)])


def test_field_values_partially_named() -> None:
    vals = FieldValues([("a", 1), (None, 2)])
    with pytest.raises(
        ValueError,
        match="This structure has some anonymous fields "
        "and therefore is not representable as a `dict`",
    ):
        _ = vals.as_dict

    assert vals.as_tuple == (1, 2)
    assert vals.a == 1
    assert vals["a"] == 1


def test_fields_from_dict() -> None:
    fields = Fields(dict(a=abi.uint(8), b=abi.bool))
    assert fields.canonical_form == "(uint8,bool)"
    assert str(fields) == "(uint8 a, bool b)"
    assert fields.decode(fields.encode([1, True])).as_dict == dict(b=True, a=1)
    assert fields.decode(fields.encode([1, True])).as_tuple == (1, True)


def test_fields_from_list() -> None:
    fields = Fields([("a", abi.uint(8)), (None, abi.bool)])
    assert str(fields) == "(uint8 a, bool)"
    assert fields.canonical_form == "(uint8,bool)"
    assert fields.decode(fields.encode([1, True])).as_tuple == (1, True)


def test_fields_from_list_simplified() -> None:
    fields = Fields([abi.uint(8), abi.bool])
    assert str(fields) == "(uint8, bool)"
    assert fields.canonical_form == "(uint8,bool)"
    assert fields.decode(fields.encode([1, True])).as_tuple == (1, True)


def test_fields_signature() -> None:
    fields = Fields(
        [
            ("assert", abi.bool),
            # can't be just replaced with `from_`, since it's already the name of another argument
            (
                "from",
                abi.bool,
            ),
            ("_4", abi.bool),  # the next argument can't be also named `_4`
            (None, abi.bool),
            ("from_", abi.bool),
            (None, abi.bool),
        ]
    )
    sig = fields.as_signature
    assert list(sig.parameters) == ["assert_", "from__1", "_4", "_4_2", "from_", "_6"]


def test_event_fields() -> None:
    fields = EventFields(dict(a=abi.uint(8), b=abi.bool, c=abi.bytes(4)), {"a", "b"})
    assert str(fields) == "(uint8 indexed a, bool indexed b, bytes4 c)"
    assert fields.canonical_form == "(uint8,bool,bytes4)"

    with pytest.raises(
        ValueError, match="All the names in `indexed` must be present in the fields list"
    ):
        EventFields(dict(a=abi.uint(8), b=abi.bool), {"a", "c"})

    with pytest.raises(
        ValueError,
        match="If `indexed` is a sequence of booleans, its length must match the number of fields",
    ):
        EventFields(dict(a=abi.uint(8), b=abi.bool), [True])


def test_event_fields_encode() -> None:
    fields = EventFields(dict(a=abi.uint(8), b=abi.bool, c=abi.bytes(4)), {"a", "b"})

    # All indexed parameters provided
    encoded = fields.encode_to_topics(1, True)
    assert encoded == ((abi.uint(8).encode(1),), (abi.bool.encode(True),))

    # One indexed parameter not provided
    encoded = fields.encode_to_topics(b=True)
    assert encoded == (None, (abi.bool.encode(True),))

    # An indexed parameter at the end not provided - the trailing Nones are trimmed
    encoded = fields.encode_to_topics(a=1)
    assert encoded == ((abi.uint(8).encode(1),),)

    # Using Either to encode several possible values for a parameter
    encoded = fields.encode_to_topics(a=Either(1, 2), b=True)
    assert encoded == (
        (abi.uint(8).encode(1), abi.uint(8).encode(2)),
        (abi.bool.encode(True),),
    )


def test_event_fields_decode() -> None:
    fields = EventFields(dict(a=abi.uint(8), b=abi.bool, c=abi.bytes(4), d=abi.bytes()), {"a", "b"})

    decoded = fields.decode_log_entry(
        [abi.uint(8).encode(1), abi.bool.encode(True)],
        encode_args((abi.bytes(4), b"1234"), (abi.bytes(), b"bytestring")),
    )
    assert decoded.as_dict == dict(a=1, b=True, c=b"1234", d=b"bytestring")

    message = re.escape(
        "The number of topics in the log entry (3) does not match "
        "the number of indexed fields in the event (2)"
    )
    with pytest.raises(ValueError, match=message):
        fields.decode_log_entry([b"1", b"2", b"3"], b"zzz")


def test_constructor_from_json() -> None:
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


def test_constructor_init() -> None:
    ctr = Constructor(inputs=dict(a=abi.uint(8), b=abi.bool), payable=True)
    assert ctr.payable
    assert ctr.inputs.canonical_form == "(uint8,bool)"
    assert str(ctr.inputs) == "(uint8 a, bool b)"

    ctr_call = ctr(1, True)
    assert ctr_call.input_bytes == b"\x00" * 31 + b"\x01" + b"\x00" * 31 + b"\x01"

    # A regression for a typo in argument passing.
    # Check that keyword arguments are processed correctly.
    ctr_call = ctr(1, b=True)
    assert ctr_call.input_bytes == b"\x00" * 31 + b"\x01" + b"\x00" * 31 + b"\x01"


def test_constructor_errors() -> None:
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


def _check_method(method: Method) -> None:
    assert method.name == "someMethod"
    assert method.inputs.canonical_form == "(uint8,bool)"
    assert str(method.inputs) == "(uint8 a, bool b)"
    assert method.outputs.canonical_form == "(uint8,bool)"

    encoded_bytes = b"\x00" * 31 + b"\x01" + b"\x00" * 31 + b"\x01"

    call = method(1, True)
    assert call.data_bytes == method.selector + encoded_bytes

    vals = method.outputs.decode(encoded_bytes)
    assert vals.as_tuple == (1, True)

    # A regression for a typo in argument passing.
    # Check that keyword arguments are processed correctly.
    call = method(1, b=True)
    assert call.data_bytes == method.selector + encoded_bytes


def test_method_from_json_anonymous_outputs() -> None:
    method = Method.from_json(
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

    assert str(method.outputs) == "(uint8, bool)"
    _check_method(method)


def test_method_from_json_named_outputs() -> None:
    method = Method.from_json(
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

    assert str(method.outputs) == "(uint8 c, bool d)"
    _check_method(method)


def test_method_init() -> None:
    method = Method(
        name="someMethod",
        mutability=Mutability.VIEW,
        inputs=dict(a=abi.uint(8), b=abi.bool),
        outputs=dict(c=abi.uint(8), d=abi.bool),
    )

    assert str(method.outputs) == "(uint8 c, bool d)"
    _check_method(method)


def test_method_single_output() -> None:
    method = Method(
        name="someMethod",
        mutability=Mutability.VIEW,
        inputs=dict(a=abi.uint(8), b=abi.bool),
        outputs=abi.uint(8),
    )

    assert method.outputs.canonical_form == "(uint8)"
    assert str(method.outputs) == "(uint8)"

    encoded_bytes = b"\x00" * 31 + b"\x01"

    # Single output is returned as a single value
    assert method.decode_output(encoded_bytes) == 1


def test_method_tuple_output() -> None:
    method = Method(
        name="someMethod",
        mutability=Mutability.VIEW,
        inputs=dict(a=abi.uint(8), b=abi.bool),
        outputs=[abi.uint(8), abi.uint(8)],
    )

    assert method.outputs.canonical_form == "(uint8,uint8)"
    assert str(method.outputs) == "(uint8, uint8)"

    encoded_bytes = b"\x00" * 31 + b"\x01" + b"\x00" * 31 + b"\x02"

    # Since all the outputs are unnamed, the output is returned as a tuple
    assert method.decode_output(encoded_bytes) == (1, 2)


def test_method_full_output() -> None:
    method = Method(
        name="someMethod",
        mutability=Mutability.VIEW,
        inputs=dict(a=abi.uint(8), b=abi.bool),
        outputs=[("a", abi.uint(8)), (None, abi.uint(8))],
    )

    assert method.outputs.canonical_form == "(uint8,uint8)"
    assert str(method.outputs) == "(uint8 a, uint8)"

    encoded_bytes = b"\x00" * 31 + b"\x01" + b"\x00" * 31 + b"\x02"

    # Since some of the outputs are named, the return value is `FieldValues`.
    assert method.decode_output(encoded_bytes).as_tuple == (1, 2)


def test_method_errors() -> None:
    with pytest.raises(
        ValueError, match="Method object must be created from a JSON entry with type='function'"
    ):
        Method.from_json(dict(type="constructor"))

    json: ABI_JSON = dict(
        type="function",
        name="someMethod",
        stateMutability="invalid",
        inputs=[
            dict(type="uint8", name="a"),
            dict(type="bool", name="b"),
        ],
    )

    with pytest.raises(ValueError, match="Unknown mutability identifier: invalid"):
        Method.from_json(json)


def test_multi_method() -> None:
    method1 = Method(
        name="someMethod",
        mutability=Mutability.VIEW,
        inputs=dict(a=abi.uint(8), b=abi.bool),
        outputs=abi.uint(8),
    )
    method2 = Method(
        name="someMethod",
        mutability=Mutability.VIEW,
        inputs=dict(a=abi.uint(8)),
        outputs=abi.uint(8),
    )

    multi_method = MultiMethod(method1, method2)
    assert multi_method["(uint8,bool)"] == method1
    assert multi_method["(uint8)"] == method2

    assert str(multi_method) == (
        "function someMethod(uint8 a, bool b) view returns (uint8); "
        "function someMethod(uint8 a) view returns (uint8)"
    )

    # Create sequentially
    multi_method = MultiMethod(method1).with_method(method2)
    assert multi_method["(uint8,bool)"] == method1
    assert multi_method["(uint8)"] == method2

    # Call the first method
    call = multi_method(1, b=True)
    assert call.method == method1

    # Call the second method
    call = multi_method(a=1)
    assert call.method == method2

    # Call with arguments not matching any of the methods
    with pytest.raises(
        TypeError, match="Could not find a suitable overloaded method for the given arguments"
    ):
        multi_method(1, True, 2)

    # If the multi-method only contains one method, raise the binding error right away
    multi_method = MultiMethod(method1)
    with pytest.raises(TypeError, match="missing a required argument: 'b'"):
        multi_method(1)


def test_multi_method_errors() -> None:
    with pytest.raises(ValueError, match="`methods` cannot be empty"):
        MultiMethod()

    method = Method(
        name="someMethod",
        mutability=Mutability.VIEW,
        inputs=dict(a=abi.uint(8), b=abi.bool),
        outputs=abi.uint(8),
    )
    method_with_different_name = Method(
        name="someMethod2",
        mutability=Mutability.VIEW,
        inputs=dict(a=abi.uint(8)),
        outputs=abi.uint(8),
    )

    with pytest.raises(ValueError, match="All overloaded methods must have the same name"):
        MultiMethod(method, method_with_different_name)

    msg = re.escape("A method someMethod(uint8,bool) is already registered in this MultiMethod")
    with pytest.raises(ValueError, match=msg):
        MultiMethod(method, method)


def test_fallback() -> None:
    fallback = Fallback.from_json(dict(type="fallback", stateMutability="payable"))
    assert fallback.payable


def test_fallback_errors() -> None:
    with pytest.raises(
        ValueError, match="Fallback object must be created from a JSON entry with type='fallback'"
    ):
        Fallback.from_json(dict(type="function", stateMutability="payable"))
    with pytest.raises(
        ValueError,
        match="Fallback method's JSON entry state mutability must be `nonpayable` or `payable`",
    ):
        Fallback.from_json(dict(type="fallback", stateMutability="view"))


def test_receive() -> None:
    receive = Receive.from_json(dict(type="receive", stateMutability="payable"))
    assert receive.payable


def test_receive_errors() -> None:
    with pytest.raises(
        ValueError, match="Receive object must be created from a JSON entry with type='receive'"
    ):
        Receive.from_json(dict(type="function", stateMutability="payable"))
    with pytest.raises(
        ValueError,
        match="Receive method's JSON entry state mutability must be `nonpayable` or `payable`",
    ):
        Receive.from_json(dict(type="receive", stateMutability="view"))


def test_contract_abi_json() -> None:
    constructor_abi: ABI_JSON = dict(
        type="constructor",
        stateMutability="payable",
        inputs=[
            dict(type="uint8", name="a"),
            dict(type="bool", name="b"),
        ],
    )

    read_abi: ABI_JSON = dict(
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

    write_abi: ABI_JSON = dict(
        type="function",
        name="writeMethod",
        stateMutability="payable",
        inputs=[
            dict(type="uint8", name="a"),
            dict(type="bool", name="b"),
        ],
    )

    event_abi: ABI_JSON = dict(
        type="event",
        name="Deposit",
        anonymous=True,
        inputs=[
            dict(indexed=True, internalType="address", name="from", type="address"),
            dict(indexed=True, internalType="bytes", name="foo", type="bytes"),
            dict(indexed=False, internalType="uint8", name="bar", type="uint8"),
        ],
    )

    error_abi: ABI_JSON = dict(
        type="error",
        name="CustomError",
        inputs=[
            dict(internalType="address", name="from", type="address"),
            dict(internalType="bytes", name="foo", type="bytes"),
            dict(internalType="uint8", name="bar", type="uint8"),
        ],
    )

    fallback_abi: ABI_JSON = dict(type="fallback", stateMutability="payable")
    receive_abi: ABI_JSON = dict(type="receive", stateMutability="payable")

    abi_json = [
        constructor_abi,
        read_abi,
        write_abi,
        fallback_abi,
        receive_abi,
        event_abi,
        error_abi,
    ]

    cabi = ContractABI.from_json(abi_json)
    assert str(cabi) == (
        "{\n"
        "    constructor(uint8 a, bool b) payable\n"
        "    fallback() payable\n"
        "    receive() payable\n"
        "    function readMethod(uint8 a, bool b) view returns (uint8, bool)\n"
        "    function writeMethod(uint8 a, bool b) payable\n"
        "    event Deposit(address indexed from, bytes indexed foo, uint8 bar) anonymous\n"
        "    error CustomError(address from, bytes foo, uint8 bar)\n"
        "}"
    )

    assert isinstance(cabi.constructor, Constructor)
    assert isinstance(cabi.fallback, Fallback)
    assert isinstance(cabi.receive, Receive)
    assert isinstance(cabi.method.readMethod, Method)
    assert isinstance(cabi.method.writeMethod, Method)
    assert isinstance(cabi.event.Deposit, Event)
    assert isinstance(cabi.error.CustomError, Error)


def clean_entries(abi: list[ABI_JSON]) -> list[ABI_JSON]:
    """
    Makes JSON ABI entries comparable.

    Currently just removes `internalType` items (we do not support keeping them at the moment).
    """
    abi = deepcopy(abi)
    for entry in abi:
        assert isinstance(entry, dict)
        if "inputs" in entry:
            for arg in entry["inputs"]:
                if "internalType" in arg:
                    del arg["internalType"]
        if "outputs" in entry:
            for arg in entry["outputs"]:
                if "internalType" in arg:
                    del arg["internalType"]

    return abi


def test_json_roundtrip() -> None:
    # Since we need the raw JSON ABI, we cannot use the existing compiler function
    # (which wraps the ABI in `ContractABI` straight away).

    compiled = solcx.compile_files(
        [Path(__file__).resolve().parent / "TestContractABI.sol"],
        output_values=["abi"],
    )

    results = {}
    for identifier, compiled_contract in compiled.items():
        _path, contract_name = identifier.split(":")
        results[contract_name] = compiled_contract["abi"]

    json_abi = results["RoundTrip"]

    cabi = ContractABI.from_json(json_abi)

    assert isinstance(json_abi, list)
    json_abi_ref = clean_entries(json_abi)

    json_abi_test = cabi.to_json()
    assert isinstance(json_abi_test, list)
    json_abi_test = clean_entries(json_abi_test)

    # The comparison is a little tricky:
    # - ABI entries are a list, and the order may have changed after the roundtrip
    # - There will be multiple entries with the same name for overloaded methods

    assert len(json_abi_ref) == len(json_abi_test)

    for ref_entry in json_abi_ref:
        matches = [entry for entry in json_abi_test if entry == ref_entry]
        assert len(matches) == 1, "expected one and only one match for each entry"


def test_contract_abi_init() -> None:
    cabi = ContractABI(
        constructor=Constructor(inputs=dict(a=abi.uint(8), b=abi.bool), payable=True),
        methods=[
            Method(
                name="readMethod",
                mutability=Mutability.VIEW,
                inputs=dict(a=abi.uint(8), b=abi.bool),
                outputs=[abi.uint(8), abi.bool],
            ),
            Method(
                name="writeMethod",
                mutability=Mutability.PAYABLE,
                inputs=dict(a=abi.uint(8), b=abi.bool),
            ),
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
        "    function readMethod(uint8 a, bool b) view returns (uint8, bool)\n"
        "    function writeMethod(uint8 a, bool b) payable\n"
        "    event Deposit(address indexed from_, bytes indexed foo, uint8 bar) anonymous\n"
        "    error CustomError(address from_, bytes foo, uint8 bar)\n"
        "}"
    )

    assert isinstance(cabi.constructor, Constructor)
    assert isinstance(cabi.fallback, Fallback)
    assert isinstance(cabi.receive, Receive)
    assert isinstance(cabi.method.readMethod, Method)
    assert isinstance(cabi.method.writeMethod, Method)


def test_overloaded_methods() -> None:
    json_abi: ABI_JSON = [
        dict(
            type="function",
            name="readMethod",
            stateMutability="view",
            inputs=[
                dict(type="uint8", name="a"),
                dict(type="bool", name="b"),
            ],
            outputs=[
                dict(type="uint8", name=""),
            ],
        ),
        dict(
            type="function",
            name="readMethod",
            stateMutability="view",
            inputs=[
                dict(type="uint8", name="a"),
            ],
            outputs=[
                dict(type="uint8", name=""),
            ],
        ),
    ]

    cabi = ContractABI.from_json(json_abi)
    assert str(cabi) == (
        "{\n"
        "    constructor() nonpayable\n"
        "    function readMethod(uint8 a, bool b) view returns (uint8)\n"
        "    function readMethod(uint8 a) view returns (uint8)\n"
        "}"
    )

    assert isinstance(cabi.method.readMethod, MultiMethod)


def test_no_constructor() -> None:
    cabi = ContractABI()
    assert isinstance(cabi.constructor, Constructor)
    assert cabi.constructor.inputs.canonical_form == "()"


def test_contract_abi_errors() -> None:
    constructor_abi = dict(type="constructor", stateMutability="payable", inputs=[])
    with pytest.raises(
        ValueError, match="JSON ABI contains more than one constructor declarations"
    ):
        ContractABI.from_json([constructor_abi, constructor_abi])

    fallback_abi = dict(type="fallback", stateMutability="payable")
    with pytest.raises(ValueError, match="JSON ABI contains more than one fallback declarations"):
        ContractABI.from_json([fallback_abi, fallback_abi])

    receive_abi = dict(type="receive", stateMutability="payable")
    with pytest.raises(
        ValueError, match="JSON ABI contains more than one receive method declarations"
    ):
        ContractABI.from_json([receive_abi, receive_abi])

    event_abi: ABI_JSON = dict(type="event", name="Foo", inputs=[], anonymous=False)
    with pytest.raises(ValueError, match="JSON ABI contains more than one declarations of `Foo`"):
        ContractABI.from_json([event_abi, event_abi])

    error_abi = dict(type="error", name="Foo", inputs=[])
    with pytest.raises(ValueError, match="JSON ABI contains more than one declarations of `Foo`"):
        ContractABI.from_json([error_abi, error_abi])

    with pytest.raises(ValueError, match="Unknown ABI entry type: foobar"):
        ContractABI.from_json([dict(type="foobar")])


def test_event_from_json() -> None:
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
    assert str(event.fields) == "(address indexed from, bytes indexed foo, uint8 bar)"


def test_event_init() -> None:
    event = Event(
        "Foo",
        dict(from_=abi.address, foo=abi.bytes(), bar=abi.uint(8)),
        indexed={"from_", "foo"},
        anonymous=True,
    )
    assert event.anonymous
    assert event.name == "Foo"
    assert str(event.fields) == "(address indexed from_, bytes indexed foo, uint8 bar)"


def test_event_encode() -> None:
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


def test_event_decode() -> None:
    event = Event("Foo", dict(a=abi.bool, b=abi.uint(8), c=abi.bytes(4), d=abi.bytes()), {"a", "b"})
    entry = LogEntry(
        topics=(
            LogTopic(keccak(event.name.encode() + event.fields.canonical_form.encode())),
            LogTopic(abi.bool.encode(True)),
            LogTopic(abi.uint(8).encode(2)),
        ),
        data=encode_args((abi.bytes(4), b"1234"), (abi.bytes(), b"bytestring")),
        # these fields do not matter for the test
        address=Address(b"0" * 20),
        removed=False,
        log_index=0,
        transaction_index=0,
        transaction_hash=TxHash(b"0" * 32),
        block_hash=BlockHash(b"0" * 32),
        block_number=0,
    )

    decoded = event.decode_log_entry(entry)
    assert decoded.as_dict == dict(a=True, b=2, c=b"1234", d=b"bytestring")


def test_event_decode_wrong_selector() -> None:
    event = Event("Foo", dict(a=abi.bool, b=abi.uint(8), c=abi.bytes(4), d=abi.bytes()), {"a", "b"})
    entry = LogEntry(
        topics=(
            LogTopic(keccak(b"NotFoo" + event.fields.canonical_form.encode())),
            LogTopic(abi.bool.encode(True)),
            LogTopic(abi.uint(8).encode(2)),
        ),
        data=encode_args((abi.bytes(4), b"1234"), (abi.bytes(), b"bytestring")),
        # these fields do not matter for the test
        address=Address(b"0" * 20),
        removed=False,
        log_index=0,
        transaction_index=0,
        transaction_hash=TxHash(b"0" * 32),
        block_hash=BlockHash(b"0" * 32),
        block_number=0,
    )

    with pytest.raises(ValueError, match="This log entry belongs to a different event"):
        event.decode_log_entry(entry)


def test_event_decode_anonymous() -> None:
    event = Event(
        "Foo",
        dict(a=abi.bool, b=abi.uint(8), c=abi.bytes(4), d=abi.bytes()),
        {"a", "b"},
        anonymous=True,
    )
    entry = LogEntry(
        topics=(LogTopic(abi.bool.encode(True)), LogTopic(abi.uint(8).encode(2))),
        data=encode_args((abi.bytes(4), b"1234"), (abi.bytes(), b"bytestring")),
        # these fields do not matter for the test
        address=Address(b"0" * 20),
        removed=False,
        log_index=0,
        transaction_index=0,
        transaction_hash=TxHash(b"0" * 32),
        block_hash=BlockHash(b"0" * 32),
        block_number=0,
    )

    decoded = event.decode_log_entry(entry)
    assert decoded.as_dict == dict(a=True, b=2, c=b"1234", d=b"bytestring")


def test_event_errors() -> None:
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


def test_error_from_json() -> None:
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


def test_error_init() -> None:
    error = Error(
        "Foo",
        dict(from_=abi.address, foo=abi.bytes(), bar=abi.uint(8)),
    )
    assert error.name == "Foo"
    assert str(error.fields) == "(address from_, bytes foo, uint8 bar)"


def test_error_decode() -> None:
    # Named fields

    error = Error(
        "Foo",
        dict(foo=abi.bytes(), bar=abi.uint(8)),
    )

    encoded_bytes = encode_args((abi.bytes(), b"12345"), (abi.uint(8), 9))
    decoded = error.decode_fields(encoded_bytes)
    assert decoded.as_dict == dict(foo=b"12345", bar=9)

    # Anonymous fields

    error = Error(
        "Foo",
        [abi.bytes(), abi.uint(8)],
    )

    encoded_bytes = encode_args((abi.bytes(), b"12345"), (abi.uint(8), 9))
    decoded = error.decode_fields(encoded_bytes)
    assert decoded.as_tuple == (b"12345", 9)


def test_resolve_error() -> None:
    error1 = Error("Error1", dict(foo=abi.bytes(), bar=abi.uint(8)))
    error2 = Error("Error2", dict(foo=abi.bool, bar=abi.string))
    contract_abi = ContractABI(errors=[error1, error2])

    # Decode custom error
    error_data = error1.selector + error1.fields.encode([b"12345", 9])
    error, decoded = contract_abi.resolve_error(error_data)
    assert error is error1
    assert decoded.as_dict == dict(foo=b"12345", bar=9)

    # Decode a panic (the description is added automatically to the ABI)
    error_data = PANIC_ERROR.selector + PANIC_ERROR.fields.encode([9])
    error, decoded = contract_abi.resolve_error(error_data)
    assert error is PANIC_ERROR
    assert decoded.as_dict == dict(code=9)

    # Decode a legacy error (the description is added automatically to the ABI)
    error_data = LEGACY_ERROR.selector + LEGACY_ERROR.fields.encode(["error message"])
    error, decoded = contract_abi.resolve_error(error_data)
    assert error is LEGACY_ERROR
    assert decoded.as_dict == dict(message="error message")

    with pytest.raises(ValueError, match="Error data too short to contain a selector"):
        contract_abi.resolve_error(b"123")

    bad_selector = b"1234"
    with pytest.raises(
        UnknownError, match=f"Could not find an error with selector {bad_selector.hex()} in the ABI"
    ):
        contract_abi.resolve_error(bad_selector + error1.fields.encode([b"12345", 9]))
