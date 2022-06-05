from eth_account import Account
import pytest

from pons import AccountSigner, Client

from .provider import EthereumTesterProvider


@pytest.fixture
def test_provider():
    yield EthereumTesterProvider()


@pytest.fixture
async def session(test_provider):
    client = Client(provider=test_provider)
    async with client.session() as session:
        yield session


@pytest.fixture
def root_signer(test_provider):
    root_account = test_provider.root_account
    yield AccountSigner(root_account)


@pytest.fixture
def another_signer():
    return AccountSigner(Account.create())
