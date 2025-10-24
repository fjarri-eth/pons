from pathlib import Path

import pytest
from ethereum_rpc import Address, BlockHash, LogEntry, LogTopic, TxHash, keccak

from pons import (
    BoundMethod,
    CompiledContract,
    Constructor,
    DeployedContract,
    Event,
    Fallback,
    Method,
    Receive,
    abi,
)
from pons._abi_types import encode_args
from pons.compiler import compile_contract_file


@pytest.fixture
def compiled_contracts() -> dict[str, CompiledContract]:
    path = Path(__file__).resolve().parent / "TestContract.sol"
    return compile_contract_file(path)


def test_abi_declaration(compiled_contracts: dict[str, CompiledContract]) -> None:
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


def test_api_binding(compiled_contracts: dict[str, CompiledContract]) -> None:
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
    assert isinstance(compiled_contract.abi.method.getState, Method)
    assert read_call.data_bytes == (
        compiled_contract.abi.method.getState.selector + b"\x00" * 31 + b"\x03"
    )
    assert read_call.decode_output(b"\x00" * 31 + b"\x04") == 4

    write_call = deployed_contract.method.setState(5)
    assert isinstance(compiled_contract.abi.method.setState, Method)
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

    log_entry = LogEntry(
        address=address,
        topics=(LogTopic(abi.uint(256).encode(1)), LogTopic(keccak(b"1234"))),
        data=encode_args((abi.bytes(4), b"4567"), (abi.bytes(), b"bytestring")),
        # These fields are not important
        removed=False,
        log_index=0,
        transaction_index=0,
        transaction_hash=TxHash(b"0" * 32),
        block_hash=BlockHash(b"0" * 32),
        block_number=0,
    )

    decoded = event_filter.decode_log_entry(log_entry)
    assert decoded.as_dict == dict(x=1, y=None, u=b"4567", v=b"bytestring")

    log_entry = LogEntry(
        address=Address(b"\xba" * 20),
        topics=(),
        data=b"",
        # These fields are not important
        removed=False,
        log_index=0,
        transaction_index=0,
        transaction_hash=TxHash(b"0" * 32),
        block_hash=BlockHash(b"0" * 32),
        block_number=0,
    )

    with pytest.raises(ValueError, match="Log entry originates from a different contract"):
        decoded = event_filter.decode_log_entry(log_entry)
