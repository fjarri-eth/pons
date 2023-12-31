import pytest

from pons import AccountSigner, Amount, Client, LocalProvider


@pytest.fixture
def test_provider():
    return LocalProvider(root_balance=Amount.ether(100))


@pytest.fixture
async def session(test_provider):
    client = Client(provider=test_provider)
    async with client.session() as session:
        yield session


@pytest.fixture
def root_signer(test_provider):
    return test_provider.root


@pytest.fixture
def another_signer():
    return AccountSigner.create()
