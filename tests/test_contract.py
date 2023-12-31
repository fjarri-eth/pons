from pathlib import Path
from typing import NamedTuple, Tuple

import pytest

from pons import (
    Address,
    Constructor,
    Event,
    Fallback,
    Method,
    Receive,
    abi,
    compile_contract_file,
)
from pons._abi_types import encode_args, keccak
from pons._contract import BoundMethod, DeployedContract
from pons._entities import LogTopic


@pytest.fixture
def compiled_contracts():
    path = Path(__file__).resolve().parent / "TestContract.sol"
    return compile_contract_file(path)


def test_abi_declaration(compiled_contracts):
    """Checks that the compiler output is parsed correctly."""
    compiled_contract = compiled_contracts["JsonAbiTest"]

    cabi = compiled_contract.abi

    assert isinstance(cabi.constructor, Constructor)
    assert str(cabi.constructor.inputs) == "(uint256 _v1, uint256 _v2)"
    assert cabi.constructor.payable

    assert isinstance(cabi.fallback, Fallback)
    assert cabi.fallback.payable
    assert isinstance(cabi.receive, Receive)
    assert cabi.receive.payable

    assert isinstance(cabi.method.v1, Method)
    assert str(cabi.method.v1.inputs) == "()"
    assert str(cabi.method.v1.outputs) == "(uint256)"

    assert isinstance(cabi.method.getState, Method)
    assert str(cabi.method.getState.inputs) == "(uint256 _x)"
    assert str(cabi.method.getState.outputs) == "(uint256)"

    assert isinstance(cabi.method.testStructs, Method)
    assert (
        str(cabi.method.testStructs.inputs)
        == "((uint256,uint256) inner_in, ((uint256,uint256),uint256) outer_in)"
    )
    assert (
        str(cabi.method.testStructs.outputs)
        == "((uint256,uint256) inner_out, ((uint256,uint256),uint256) outer_out)"
    )

    assert isinstance(cabi.method.setState, Method)
    assert str(cabi.method.setState.inputs) == "(uint256 _v1)"
    assert cabi.method.setState.payable

    assert isinstance(cabi.event.Foo, Event)
    assert str(cabi.event.Foo.fields) == "(uint256 indexed x, bytes indexed y, bytes4 u, bytes v)"
    assert cabi.event.Foo.anonymous
    assert cabi.event.Foo.indexed == {"x", "y"}


def test_api_binding(compiled_contracts):
    """Checks that the methods are bound correctly on deploy."""
    compiled_contract = compiled_contracts["JsonAbiTest"]

    address = Address(b"\xab" * 20)
    deployed_contract = DeployedContract(compiled_contract.abi, address)

    assert deployed_contract.address == address
    assert deployed_contract.abi == compiled_contract.abi
    assert isinstance(deployed_contract.method.v1, BoundMethod)
    assert isinstance(deployed_contract.method.getState, BoundMethod)
    assert isinstance(deployed_contract.method.testStructs, BoundMethod)
    assert isinstance(deployed_contract.method.setState, BoundMethod)

    ctr_call = compiled_contract.constructor(1, 2)
    assert ctr_call.payable
    assert ctr_call.contract_abi == compiled_contract.abi
    assert ctr_call.data_bytes == (
        compiled_contract.bytecode + b"\x00" * 31 + b"\x01" + b"\x00" * 31 + b"\x02"
    )

    read_call = deployed_contract.method.getState(3)
    assert read_call.contract_address == address
    assert read_call.data_bytes == (
        compiled_contract.abi.method.getState.selector + b"\x00" * 31 + b"\x03"
    )
    assert read_call.decode_output(b"\x00" * 31 + b"\x04") == (4,)

    write_call = deployed_contract.method.setState(5)
    assert write_call.contract_address == address
    assert write_call.payable
    assert write_call.data_bytes == (
        compiled_contract.abi.method.setState.selector + b"\x00" * 31 + b"\x05"
    )

    event_filter = deployed_contract.event.Foo(1, b"1234")
    assert event_filter.contract_address == address
    assert event_filter.topics == (
        (LogTopic(abi.uint(256).encode(1)),),
        (LogTopic(keccak(b"1234")),),
    )

    # We only need a couple of fields
    class FakeLogEntry(NamedTuple):
        data: bytes
        address: Address
        topics: Tuple[LogTopic, ...]

    decoded = event_filter.decode_log_entry(
        FakeLogEntry(
            address=address,
            topics=[LogTopic(abi.uint(256).encode(1)), LogTopic(keccak(b"1234"))],
            data=encode_args((abi.bytes(4), b"4567"), (abi.bytes(), b"bytestring")),
        )
    )
    assert decoded == dict(x=1, y=None, u=b"4567", v=b"bytestring")

    with pytest.raises(ValueError, match="Log entry originates from a different contract"):
        decoded = event_filter.decode_log_entry(
            FakeLogEntry(address=Address(b"\xba" * 20), topics=[], data=b"")
        )
