import os
from pathlib import Path

import pytest

from pons import (
    AccountSigner,
    ClientSession,
    CompiledContract,
    get_create2_address,
    get_create_address,
)
from pons.compiler import compile_contract_file


@pytest.fixture
def compiled_contracts() -> dict[str, CompiledContract]:
    path = Path(__file__).resolve().parent / "TestUtils.sol"
    return compile_contract_file(path)


async def test_create(
    session: ClientSession,
    root_signer: AccountSigner,
    compiled_contracts: dict[str, CompiledContract],
) -> None:
    compiled_to_deploy = compiled_contracts["ToDeploy"]

    # Try deploying the contract with different nonces

    nonce = await session.rpc.eth_get_transaction_count(root_signer.address)
    assert nonce == 0
    to_deploy = await session.deploy(root_signer, compiled_to_deploy.constructor(123))
    assert to_deploy.address == get_create_address(root_signer.address, nonce)

    nonce = await session.rpc.eth_get_transaction_count(root_signer.address)
    assert nonce == 1
    to_deploy = await session.deploy(root_signer, compiled_to_deploy.constructor(123))
    assert to_deploy.address == get_create_address(root_signer.address, nonce)

    nonce = await session.rpc.eth_get_transaction_count(root_signer.address)
    assert nonce == 2
    to_deploy = await session.deploy(root_signer, compiled_to_deploy.constructor(123))
    assert to_deploy.address == get_create_address(root_signer.address, nonce)


async def test_create2(
    session: ClientSession,
    root_signer: AccountSigner,
    compiled_contracts: dict[str, CompiledContract],
) -> None:
    compiled_deployer = compiled_contracts["Create2Deployer"]
    compiled_to_deploy = compiled_contracts["ToDeploy"]

    deployer = await session.deploy(root_signer, compiled_deployer.constructor())

    salt = os.urandom(32)
    to_deploy = compiled_to_deploy.constructor(123)
    events = await session.transact(
        root_signer,
        deployer.method.deploy(to_deploy.data_bytes, salt),
        return_events=[deployer.event.Deployed],
    )
    assert len(events[deployer.event.Deployed]) == 1
    assert events[deployer.event.Deployed][0] == dict(
        deployedAddress=get_create2_address(deployer.address, to_deploy.data_bytes, salt)
    )

    with pytest.raises(ValueError, match="Salt must be 32 bytes in length"):
        get_create2_address(deployer.address, to_deploy.data_bytes, salt[:-1])
