from pathlib import Path

import pytest

from pons import (
    Amount,
    ContractABI,
    abi,
    Constructor,
    ReadMethod,
    WriteMethod,
    DeployedContract,
)

from .compile import compile_file


@pytest.fixture
def compiled_contracts():
    path = Path(__file__).resolve().parent / "TestContractFunctionality.sol"
    yield compile_file(path)


async def test_empty_constructor(session, root_signer, compiled_contracts):
    """
    Checks that an empty constructor is created automatically if none is provided,
    and it can be used to deploy the contract.
    """

    compiled_contract = compiled_contracts["NoConstructor"]

    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor())
    call = deployed_contract.read.getState(123)
    result = await session.eth_call(call)
    assert result == (1 + 123,)


async def test_basics(session, root_signer, another_signer, compiled_contracts):

    compiled_contract = compiled_contracts["Test"]

    # Deploy the contract
    call = compiled_contract.constructor(12345, 56789)
    await session.transfer(root_signer, another_signer.address, Amount.ether(10))
    deployed_contract = await session.deploy(another_signer, call)

    # Check the state
    assert await session.eth_call(deployed_contract.read.v1()) == (12345,)
    assert await session.eth_call(deployed_contract.read.v2()) == (56789,)

    # Transact with the contract
    await session.transact(another_signer, deployed_contract.write.setState(111))
    assert await session.eth_call(deployed_contract.read.v1()) == (111,)

    # Call the contract

    result = await session.eth_call(deployed_contract.read.getState(123))
    assert result == (111 + 123,)

    inner = dict(inner1=1, inner2=2)
    outer = dict(inner=inner, outer1=3)
    result = await session.eth_call(deployed_contract.read.testStructs(inner, outer))
    assert result == (inner, outer)


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
        write=[WriteMethod(name="setState", inputs=dict(_v1=abi.uint(256)))],
        read=[
            ReadMethod(name="getState", inputs=dict(_x=abi.uint(256)), outputs=abi.uint(256)),
            ReadMethod(
                name="testStructs",
                inputs=dict(inner_in=inner_struct, outer_in=outer_struct),
                outputs=dict(inner_out=inner_struct, outer_out=outer_struct),
            ),
        ],
    )

    deployed_contract = DeployedContract(declared_abi, previously_deployed_contract.address)

    # Transact with the contract
    await session.transfer(root_signer, another_signer.address, Amount.ether(10))
    await session.transact(another_signer, deployed_contract.write.setState(111))

    # Call the contract

    result = await session.eth_call(deployed_contract.read.getState(123))
    assert result == 111 + 123  # Note the lack of `[]` - we declared outputs as a single value

    inner = dict(inner1=1, inner2=2)
    outer = dict(inner=inner, outer1=3)
    result = await session.eth_call(deployed_contract.read.testStructs(inner, outer))
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
    await session.transact(root_signer, contract.write.emitComplicated())
    entries_filtered = await session.eth_get_filter_changes(log_filter1)
    entries_all = await session.eth_get_filter_changes(log_filter2)

    assert len(entries_all) == 1
    assert entries_filtered == entries_all
