import pytest

from pons import AccountSigner, Amount, Client, TesterProvider


# Masking the global fixtures to make this test self-contained
# (since TesterProvider is what we're testing).
@pytest.fixture
def provider():
    yield TesterProvider(root_balance=Amount.ether(100))


@pytest.fixture
async def session(provider):
    client = Client(provider=provider)
    async with client.session() as session:
        yield session


@pytest.fixture
def root_signer(provider):
    yield provider.root


@pytest.fixture
def another_signer():
    return AccountSigner.create()


async def test_root_balance():
    amount = Amount.ether(123)
    provider = TesterProvider(root_balance=amount)
    client = Client(provider=provider)
    async with client.session() as session:
        assert await session.eth_get_balance(provider.root.address) == amount


async def test_auto_mine(provider, session, root_signer, another_signer):
    # Auto-mininig is the default behavior
    tx_hash = await session.broadcast_transfer(root_signer, another_signer.address, Amount.ether(1))
    receipt = await session.eth_get_transaction_receipt(tx_hash)
    assert receipt.succeeded

    # Disable auto-mining. Now broadcasting the transaction does not automatically finalize it.
    provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(root_signer, another_signer.address, Amount.ether(1))
    receipt = await session.eth_get_transaction_receipt(tx_hash)
    assert receipt is None

    # Enable auto-mining back. The pending transactions are added to the block.
    provider.enable_auto_mine_transactions()
    receipt = await session.eth_get_transaction_receipt(tx_hash)
    assert receipt.succeeded
