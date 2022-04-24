from pathlib import Path

from eth_account import Account
import pytest
import trio

from pons import (
    Client,
    AccountSigner,
    Address,
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


async def test_empty_constructor(test_provider, compiled_contracts):
    """
    Checks that an empty constructor is created automatically if none is provided,
    and it can be used to deploy the contract.
    """

    compiled_contract = compiled_contracts["NoConstructor"]

    client = Client(provider=test_provider)

    root_account = test_provider.root_account
    root_signer = AccountSigner(root_account)
    root_address = Address.from_hex(root_account.address)

    async with client.session() as session:
        deployed_contract = await session.deploy(root_signer, compiled_contract.constructor())
        call = deployed_contract.read.getState(123)
        result = await session.eth_call(call)
        assert result == [1 + 123]


async def test_basics(test_provider, compiled_contracts):

    compiled_contract = compiled_contracts["Test"]

    client = Client(provider=test_provider)

    root_account = test_provider.root_account
    root_signer = AccountSigner(root_account)

    acc1 = Account.create()
    acc1_signer = AccountSigner(acc1)

    root_address = Address.from_hex(root_account.address)
    acc1_address = Address.from_hex(acc1.address)

    async with client.session() as session:

        # Fund the deployer account
        await session.transfer(root_signer, acc1_address, Amount.ether(10))

        # Deploy the contract
        call = compiled_contract.constructor(12345, 56789)
        deployed_contract = await session.deploy(acc1_signer, call)

        # Check the state
        assert await session.eth_call(deployed_contract.read.v1()) == [12345]
        assert await session.eth_call(deployed_contract.read.v2()) == [56789]

        # Transact with the contract
        await session.transact(acc1_signer, deployed_contract.write.setState(111))
        assert await session.eth_call(deployed_contract.read.v1()) == [111]

        # Call the contract

        result = await session.eth_call(deployed_contract.read.getState(123))
        assert result == [111 + 123]

        inner = dict(inner1=1, inner2=2)
        outer = dict(inner=inner, outer1=3)
        result = await session.eth_call(deployed_contract.read.testStructs(inner, outer))
        assert result == [inner, outer]


async def test_abi_declaration(test_provider, compiled_contracts):

    compiled_contract = compiled_contracts["Test"]

    client = Client(provider=test_provider)

    root_account = test_provider.root_account
    root_signer = AccountSigner(root_account)

    acc1 = Account.create()
    acc1_signer = AccountSigner(acc1)

    root_address = Address.from_hex(root_account.address)
    acc1_address = Address.from_hex(acc1.address)

    async with client.session() as session:

        # Fund the deployer account
        await session.transfer(root_signer, acc1_address, Amount.ether(10))

        # Deploy the contract
        call = compiled_contract.constructor(12345, 56789)
        previously_deployed_contract = await session.deploy(acc1_signer, call)

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

    async with client.session() as session:

        # Transact with the contract
        await session.transact(acc1_signer, deployed_contract.write.setState(111))

        # Call the contract

        result = await session.eth_call(deployed_contract.read.getState(123))
        assert result == 111 + 123  # Note the lack of `[]` - we declared outputs as a single value

        inner = dict(inner1=1, inner2=2)
        outer = dict(inner=inner, outer1=3)
        result = await session.eth_call(deployed_contract.read.testStructs(inner, outer))
        assert result == [inner, outer]
