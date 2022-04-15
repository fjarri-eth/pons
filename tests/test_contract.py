import pytest
from pathlib import Path

import pytest

from pons import *

from .compile import compile_contract


@pytest.fixture
def compiled_contract():
    path = Path(__file__).resolve().parent / 'TestContract.sol'
    yield compile_contract(path)


def test_bind():
    inner_struct = Struct(dict(inner1=uint256, inner2=uint256))
    outer_struct = Struct(dict(inner=inner_struct, outer1=uint256))
    method = Method.pure(
        name='testStructs',
        inputs=dict(inner_in=inner_struct, outer_in=outer_struct),
        outputs=dict(inner_out=inner_struct, outer_out=outer_struct),
        )

    # TODO: check that we can use NamedTuples or attr objects too
    inner = dict(inner1=1, inner2=2)
    outer = dict(inner=inner, outer1=3)
    call = method(inner, outer)


async def test_abi_declaration(test_provider, compiled_contract):

    client = Client(provider=test_provider)

    root_account = test_provider.root_account
    root_signer = AccountSigner(root_account)
    root_address = Address.from_hex(root_account.address)

    # The contract was deployed earlier
    async with client.session() as session:
        deployed_contract = await session.deploy(root_signer, compiled_contract, 12345, 56789)

    # Now all we have is this
    inner_struct = Struct(dict(inner1=uint256, inner2=uint256))
    outer_struct = Struct(dict(inner=inner_struct, outer1=uint256))
    abi = ContractABI(
        constructor=Constructor.nonpayable(inputs=dict(_v1=uint256, _v2=uint256)),
        methods=[
            Method.nonpayable(name='setState', inputs=dict(_v1=uint256)),
            Method.view(name='getState', unique_name='getState_v1', inputs=dict(_x=uint256), outputs=uint256),
            Method.view(name='getState', unique_name='getState_v2', inputs=dict(_x=uint256, _y=uint256), outputs=uint256),
            Method.pure(
                name='testStructs',
                inputs=dict(inner_in=inner_struct, outer_in=outer_struct),
                outputs=dict(inner_out=inner_struct, outer_out=outer_struct),
                )
            ]
        )

    contract_address = deployed_contract.address
    deployed_contract = DeployedContract(abi, contract_address)

    async with client.session() as session:

        # Transact with the contract

        call = deployed_contract.abi.method.setState(111)
        await session.transact(root_signer, contract_address, call)

        # Call the contract

        call = deployed_contract.abi.method.getState_v1(123)
        result = await session.call(contract_address, call)
        assert result == 111 + 123

        call = deployed_contract.abi.method.getState_v2(123, 456)
        result = await session.call(contract_address, call)
        assert result == 111 + 123 + 456

        inner = dict(inner1=1, inner2=2)
        outer = dict(inner=inner, outer1=3)
        call = deployed_contract.abi.method.testStructs(inner, outer)
        result = await session.call(contract_address, call)
        assert result == [inner, outer]
