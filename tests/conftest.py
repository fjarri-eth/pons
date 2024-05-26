import pytest
from ethereum_rpc import Amount

from pons import AccountSigner, Client, LocalProvider


@pytest.fixture
def local_provider():
    return LocalProvider(root_balance=Amount.ether(100))


@pytest.fixture
async def session(local_provider):
    client = Client(provider=local_provider)
    async with client.session() as session:
        yield session


@pytest.fixture
def root_signer(local_provider):
    return local_provider.root


@pytest.fixture
def another_signer():
    return AccountSigner.create()
