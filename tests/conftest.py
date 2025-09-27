from collections.abc import AsyncIterator

import pytest
from alysis import EVMVersion
from ethereum_rpc import Amount

from pons import AccountSigner, Client, ClientSession, LocalProvider


@pytest.fixture
def local_provider() -> LocalProvider:
    return LocalProvider(root_balance=Amount.ether(100), evm_version=EVMVersion.CANCUN)


@pytest.fixture
async def session(local_provider: LocalProvider) -> AsyncIterator[ClientSession]:
    client = Client(provider=local_provider)
    async with client.session() as session:
        yield session


@pytest.fixture
def root_signer(local_provider: LocalProvider) -> AccountSigner:
    return local_provider.root


@pytest.fixture
def another_signer() -> AccountSigner:
    return AccountSigner.create()
