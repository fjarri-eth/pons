import pytest
from pathlib import Path

import pytest

from pons import abi
from pons import *

from .compile import compile_contract


@pytest.fixture
def compiled_contract():
    path = Path(__file__).resolve().parent / 'TestContract.sol'
    yield compile_contract(path)


async def test_abi_declaration(test_provider, compiled_contract):

    client = Client(provider=test_provider)

    root_account = test_provider.root_account
    root_signer = AccountSigner(root_account)
    root_address = Address.from_hex(root_account.address)

    # The contract was deployed earlier
    async with client.session() as session:
        deployed_contract = await session.deploy(root_signer, compiled_contract.constructor(12345, 56789))

    # Now all we have is this
    inner_struct = Struct(dict(inner1=abi.uint(256), inner2=abi.uint(256)))
    outer_struct = Struct(dict(inner=inner_struct, outer1=abi.uint(256)))
    declared_abi = ContractABI(
        constructor=Constructor(inputs=dict(_v1=abi.uint(256), _v2=abi.uint(256))),
        write=[
            WriteMethod(name='setState', inputs=dict(_v1=abi.uint(256)))
        ],
        read=[
            ReadMethod(name='getState', inputs=dict(_x=abi.uint(256)), outputs=abi.uint(256)),
            ReadMethod(
                name='testStructs',
                inputs=dict(inner_in=inner_struct, outer_in=outer_struct),
                outputs=dict(inner_out=inner_struct, outer_out=outer_struct),
                )
            ]
        )

    contract_address = deployed_contract.address
    deployed_contract = DeployedContract(declared_abi, contract_address)

    async with client.session() as session:

        # Transact with the contract

        call = deployed_contract.write.setState(111)
        await session.transact(root_signer, call)

        # Call the contract

        call = deployed_contract.read.getState(123)
        result = await session.call(call)
        assert result == 111 + 123

        inner = dict(inner1=1, inner2=2)
        outer = dict(inner=inner, outer1=3)
        call = deployed_contract.read.testStructs(inner, outer)
        result = await session.call(call)
        assert result == [inner, outer]
