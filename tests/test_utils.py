import os
from pathlib import Path

import pytest

from pons import EVMVersion, compile_contract_file, get_create2_address


@pytest.fixture
def compiled_contracts():
    path = Path(__file__).resolve().parent / "TestUtils.sol"
    return compile_contract_file(path, evm_version=EVMVersion.CANCUN)


async def test_create2(session, root_signer, compiled_contracts):
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
