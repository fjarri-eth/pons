from collections import namedtuple
from pathlib import Path

import pytest

from pons import (
    abi,
    Address,
    Constructor,
    ReadMethod,
    WriteMethod,
    Fallback,
    Receive,
    Event,
)
from pons._abi_types import keccak, encode_args
from pons._contract import DeployedContract, BoundReadMethod, BoundWriteMethod
from pons._entities import LogTopic

from .compile import compile_file


@pytest.fixture
def compiled_contracts():
    path = Path(__file__).resolve().parent / "TestContract.sol"
    yield compile_file(path)


def test_abi_declaration(compiled_contracts):
    """
    Checks that the compiler output is parsed correctly.
    """

    compiled_contract = compiled_contracts["JsonAbiTest"]

    cabi = compiled_contract.abi

    assert isinstance(cabi.constructor, Constructor)
    assert str(cabi.constructor.inputs) == "(uint256 _v1, uint256 _v2)"
    assert cabi.constructor.payable

    assert isinstance(cabi.fallback, Fallback)
    assert cabi.fallback.payable
    assert isinstance(cabi.receive, Receive)
    assert cabi.receive.payable

    assert isinstance(cabi.read.v1, ReadMethod)
    assert str(cabi.read.v1.inputs) == "()"
    assert str(cabi.read.v1.outputs) == "(uint256)"

    assert isinstance(cabi.read.getState, ReadMethod)
    assert str(cabi.read.getState.inputs) == "(uint256 _x)"
    assert str(cabi.read.getState.outputs) == "(uint256)"

    assert isinstance(cabi.read.testStructs, ReadMethod)
    assert (
        str(cabi.read.testStructs.inputs)
        == "((uint256,uint256) inner_in, ((uint256,uint256),uint256) outer_in)"
    )
    assert (
        str(cabi.read.testStructs.outputs)
        == "((uint256,uint256) inner_out, ((uint256,uint256),uint256) outer_out)"
    )

    assert isinstance(cabi.write.setState, WriteMethod)
    assert str(cabi.write.setState.inputs) == "(uint256 _v1)"
    assert cabi.write.setState.payable

    assert isinstance(cabi.event.Foo, Event)
    assert str(cabi.event.Foo.fields) == "(uint256 indexed x, bytes indexed y, bytes4 u, bytes v)"
    assert cabi.event.Foo.anonymous
    assert cabi.event.Foo.indexed == {"x", "y"}


def test_api_binding(compiled_contracts):
    """
    Checks that the methods are bound correctly on deploy.
    """

    compiled_contract = compiled_contracts["JsonAbiTest"]

    address = Address(b"\xab" * 20)
    deployed_contract = DeployedContract(compiled_contract.abi, address)

    assert deployed_contract.address == address
    assert deployed_contract.abi == compiled_contract.abi
    assert isinstance(deployed_contract.read.v1, BoundReadMethod)
    assert isinstance(deployed_contract.read.getState, BoundReadMethod)
    assert isinstance(deployed_contract.read.testStructs, BoundReadMethod)
    assert isinstance(deployed_contract.write.setState, BoundWriteMethod)

    ctr_call = compiled_contract.constructor(1, 2)
    assert ctr_call.payable
    assert ctr_call.contract_abi == compiled_contract.abi
    assert ctr_call.data_bytes == (
        compiled_contract.bytecode + b"\x00" * 31 + b"\x01" + b"\x00" * 31 + b"\x02"
    )

    read_call = deployed_contract.read.getState(3)
    assert read_call.contract_address == address
    assert read_call.data_bytes == (
        compiled_contract.abi.read.getState.selector + b"\x00" * 31 + b"\x03"
    )
    assert read_call.decode_output(b"\x00" * 31 + b"\x04") == (4,)

    write_call = deployed_contract.write.setState(5)
    assert write_call.contract_address == address
    assert write_call.payable
    assert write_call.data_bytes == (
        compiled_contract.abi.write.setState.selector + b"\x00" * 31 + b"\x05"
    )

    event_filter = deployed_contract.event.Foo(1, b"1234")
    assert event_filter.contract_address == address
    assert event_filter.topics == (
        (LogTopic(abi.uint(256).encode(1)),),
        (LogTopic(keccak(b"1234")),),
    )

    # We only need a couple of fields
    fake_log_entry = namedtuple("fake_log_entry", ["topics", "data", "address"])
    decoded = event_filter.decode_log_entry(
        fake_log_entry(
            address=address,
            topics=[LogTopic(abi.uint(256).encode(1)), LogTopic(keccak(b"1234"))],
            data=encode_args((abi.bytes(4), b"4567"), (abi.bytes(), b"bytestring")),
        )
    )
    assert decoded == dict(x=1, y=None, u=b"4567", v=b"bytestring")

    with pytest.raises(ValueError, match="Log entry originates from a different contract"):
        decoded = event_filter.decode_log_entry(
            fake_log_entry(address=Address(b"\xba" * 20), topics=[], data=b"")
        )
