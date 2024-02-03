from pathlib import Path

import pytest

from pons import (
    Amount,
    Constructor,
    ContractABI,
    DeployedContract,
    Method,
    Mutability,
    abi,
)
from pons._compiler import compile_contract_file


@pytest.fixture
def compiled_contracts():
    path = Path(__file__).resolve().parent / "TestContractFunctionality.sol"
    return compile_contract_file(path)


async def test_empty_constructor(session, root_signer, compiled_contracts):
    """
    Checks that an empty constructor is created automatically if none is provided,
    and it can be used to deploy the contract.
    """
    compiled_contract = compiled_contracts["NoConstructor"]

    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor())
    call = deployed_contract.method.getState(123)
    result = await session.eth_call(call)
    assert result == (1 + 123,)


async def test_basics(session, root_signer, another_signer, compiled_contracts):
    compiled_contract = compiled_contracts["Test"]

    # Deploy the contract
    call = compiled_contract.constructor(12345, 56789)
    await session.transfer(root_signer, another_signer.address, Amount.ether(10))
    deployed_contract = await session.deploy(another_signer, call)

    # Check the state
    assert await session.eth_call(deployed_contract.method.v1()) == (12345,)
    assert await session.eth_call(deployed_contract.method.v2()) == (56789,)

    # Transact with the contract
    await session.transact(another_signer, deployed_contract.method.setState(111))
    assert await session.eth_call(deployed_contract.method.v1()) == (111,)

    # Call the contract

    result = await session.eth_call(deployed_contract.method.getState(123))
    assert result == (111 + 123,)

    inner = dict(inner1=1, inner2=2)
    outer = dict(inner=inner, outer1=3)
    result = await session.eth_call(deployed_contract.method.testStructs(inner, outer))
    assert result == (inner, outer)


async def test_overloaded_method(session, root_signer, compiled_contracts):
    compiled_contract = compiled_contracts["Test"]

    # Deploy the contract
    call = compiled_contract.constructor(12345, 56789)
    deployed_contract = await session.deploy(root_signer, call)

    result = await session.eth_call(deployed_contract.method.overloaded(123))
    assert result == (12345 + 123,)

    result = await session.eth_call(deployed_contract.method.overloaded(123, 456))
    assert result == (456 + 123,)


async def test_read_only_mode(session, root_signer, compiled_contracts):
    # Test that a "nonpayable" (that is, mutating) method can still be invoked
    # via `eth_call`, and it will use the current state of the contract
    # in a "copy-on-write" mode, where it will be able to make changes,
    # but they will not be saved.

    compiled_contract = compiled_contracts["Test"]

    value = 12345
    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor(value, 0))

    # check the state
    result = await session.eth_call(deployed_contract.method.getState(0))
    assert result == (value,)

    # this method will not modify the state since it's invoked via `eth_call`,
    # but it will return a value that reflects the ethereal "modified" state.
    result = await session.eth_call(deployed_contract.method.setStateAndReturn(1))
    assert result == (value + 1,)

    result = await session.eth_call(deployed_contract.method.getState(0))
    assert result == (value,)

    # Now invoke it as a transaction, allowing it to modify the state
    await session.transact(root_signer, deployed_contract.method.setStateAndReturn(1))

    # The state is now modified
    result = await session.eth_call(deployed_contract.method.getState(0))
    assert result == (value + 1,)


async def test_abi_declaration(session, root_signer, another_signer, compiled_contracts):
    compiled_contract = compiled_contracts["Test"]

    # Deploy the contract
    await session.transfer(root_signer, another_signer.address, Amount.ether(10))
    call = compiled_contract.constructor(12345, 56789)
    previously_deployed_contract = await session.deploy(another_signer, call)

    # The contract was deployed earlier, now all we have is this
    inner_struct = abi.struct(inner1=abi.uint(256), inner2=abi.uint(256))
    outer_struct = abi.struct(inner=inner_struct, outer1=abi.uint(256))
    declared_abi = ContractABI(
        constructor=Constructor(inputs=dict(_v1=abi.uint(256), _v2=abi.uint(256))),
        methods=[
            Method(
                name="setState", mutability=Mutability.NONPAYABLE, inputs=dict(_v1=abi.uint(256))
            ),
            Method(
                name="getState",
                mutability=Mutability.VIEW,
                inputs=dict(_x=abi.uint(256)),
                outputs=abi.uint(256),
            ),
            Method(
                name="testStructs",
                mutability=Mutability.VIEW,
                inputs=dict(inner_in=inner_struct, outer_in=outer_struct),
                outputs=dict(inner_out=inner_struct, outer_out=outer_struct),
            ),
        ],
    )

    deployed_contract = DeployedContract(declared_abi, previously_deployed_contract.address)

    # Transact with the contract
    await session.transfer(root_signer, another_signer.address, Amount.ether(10))
    await session.transact(another_signer, deployed_contract.method.setState(111))

    # Call the contract

    result = await session.eth_call(deployed_contract.method.getState(123))
    assert result == 111 + 123  # Note the lack of `[]` - we declared outputs as a single value

    inner = dict(inner1=1, inner2=2)
    outer = dict(inner=inner, outer1=3)
    result = await session.eth_call(deployed_contract.method.testStructs(inner, outer))
    assert result == (inner, outer)


async def test_complicated_event(session, root_signer, compiled_contracts):
    # Smoke test for topic encoding, emitting an event with non-trivial topic structure.
    # The details of the encoding should be covered in ABI tests,
    # here we're just checking we got them right.

    basic_contract = compiled_contracts["Test"]

    bytestring33len1 = b"012345678901234567890123456789012"
    bytestring33len2 = b"-12345678901234567890123456789012"
    inner1 = [b"0123", bytestring33len1]
    inner2 = [b"-123", bytestring33len2]
    foo = [b"4567", [b"aa", b"bb"], bytestring33len1, "\u1234\u1212", inner1]
    event_filter = basic_contract.abi.event.Complicated(
        b"aaaa", bytestring33len2, foo, [inner1, inner2]
    )

    contract = await session.deploy(root_signer, basic_contract.constructor(123, 456))

    log_filter1 = await session.eth_new_filter(event_filter=event_filter)  # filter by topics
    log_filter2 = await session.eth_new_filter()  # collect everything
    await session.transact(root_signer, contract.method.emitComplicated())
    entries_filtered = await session.eth_get_filter_changes(log_filter1)
    entries_all = await session.eth_get_filter_changes(log_filter2)

    assert len(entries_all) == 1
    assert entries_filtered == entries_all
