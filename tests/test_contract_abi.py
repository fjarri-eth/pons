import pytest

from pons import abi, Constructor, ReadMethod, WriteMethod, Fallback, Receive, ContractABI
from pons._contract_abi import Signature, ABIDecodingError


def test_signature_from_dict():
    sig = Signature(dict(a=abi.uint(8), b=abi.bool))
    assert sig.canonical_form == ("(uint8,bool)")
    assert str(sig) == "(uint8 a, bool b)"
    assert sig.decode(sig.encode(1, True)) == [1, True]
    assert sig.decode(sig.encode(b=True, a=1)) == [1, True]
    assert sig.decode(sig.encode_single(dict(b=True, a=1))) == [1, True]
    assert sig.decode(sig.encode_single([1, True])) == [1, True]


def test_signature_from_list():
    sig = Signature([abi.uint(8), abi.bool])
    assert str(sig) == "(uint8, bool)"
    assert sig.canonical_form == "(uint8,bool)"
    assert sig.decode(sig.encode(1, True)) == [1, True]
    assert sig.decode(sig.encode_single([1, True])) == [1, True]


def test_encode_non_iterable():
    sig = Signature(dict(a=abi.uint(8)))
    assert sig.decode(sig.encode_single(1)) == [1]


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
        ctr = Constructor.from_json(dict(type="function"))

    with pytest.raises(ValueError, match="Constructor's JSON entry cannot have a `name`"):
        ctr = Constructor.from_json(dict(type="constructor", name="myConstructor"))

    with pytest.raises(
        ValueError, match="Constructor's JSON entry cannot have non-empty `outputs`"
    ):
        ctr = Constructor.from_json(
            dict(type="constructor", outputs=[dict(type="uint8", name="a")])
        )

    # This is fine though
    ctr = Constructor.from_json(dict(type="constructor", outputs=[], stateMutability="nonpayable"))

    with pytest.raises(
        ValueError,
        match="Constructor's JSON entry state mutability must be `nonpayable` or `payable`",
    ):
        ctr = Constructor.from_json(dict(type="constructor", stateMutability="view"))


def _check_read_method(read):
    assert read.name == "someMethod"
    assert read.inputs.canonical_form == "(uint8,bool)"
    assert str(read.inputs) == "(uint8 a, bool b)"
    assert read.outputs.canonical_form == "(uint8,bool)"

    encoded_bytes = b"\x00" * 31 + b"\x01" + b"\x00" * 31 + b"\x01"

    rcall = read(1, True)
    assert rcall.data_bytes == read.selector + encoded_bytes

    vals = read.decode_output(encoded_bytes)
    assert vals == [1, True]


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


async def test_decoding_error():
    """
    Checks handling of an event when data returned by `eth_call` does not match
    the output signature of the method.
    """
    read = ReadMethod(name="someMethod", inputs=[], outputs=[abi.uint(256), abi.uint(256)])

    encoded_bytes = b"\x00" * 31 + b"\x01"  # Only one uint256

    expected_message = (
        r"Could not decode the return value with the expected signature \(uint256,uint256\): "
        r"Tried to read 32 bytes.  Only got 0 bytes"
    )

    with pytest.raises(ABIDecodingError, match=expected_message):
        read.decode_output(encoded_bytes)


def test_read_method_errors():
    with pytest.raises(
        ValueError, match="ReadMethod object must be created from a JSON entry with type='function'"
    ):
        ctr = ReadMethod.from_json(dict(type="constructor"))

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
        ctr = WriteMethod.from_json(dict(type="constructor"))

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

    fallback_abi = dict(type="fallback", stateMutability="payable")
    receive_abi = dict(type="receive", stateMutability="payable")

    cabi = ContractABI.from_json([constructor_abi, read_abi, write_abi, fallback_abi, receive_abi])
    assert str(cabi) == (
        "{\n"
        "    constructor(uint8 a, bool b) payable\n"
        "    fallback() payable\n"
        "    receive() payable\n"
        "    function readMethod(uint8 a, bool b) returns (uint8, bool)\n"
        "    function writeMethod(uint8 a, bool b) payable\n"
        "}"
    )

    assert isinstance(cabi.constructor, Constructor)
    assert isinstance(cabi.fallback, Fallback)
    assert isinstance(cabi.receive, Receive)
    assert isinstance(cabi.read.readMethod, ReadMethod)
    assert isinstance(cabi.write.writeMethod, WriteMethod)


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

    with pytest.raises(ValueError, match="Unknown ABI entry type: event"):
        abi = ContractABI.from_json([dict(type="event")])
