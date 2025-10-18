import re
from collections.abc import AsyncIterator

import pytest
from ethereum_rpc import Amount

from pons import AccountSigner, Client, ClientSession, LocalProvider, ProviderError


# Masking the global fixtures to make this test self-contained
# (since LocalProvider is what we're testing).
@pytest.fixture
def provider() -> LocalProvider:
    return LocalProvider(root_balance=Amount.ether(100))


@pytest.fixture
async def session(provider: LocalProvider) -> AsyncIterator[ClientSession]:
    client = Client(provider=provider)
    async with client.session() as session:
        yield session


@pytest.fixture
def root_signer(provider: LocalProvider) -> AccountSigner:
    return provider.root


@pytest.fixture
def another_signer() -> AccountSigner:
    return AccountSigner.create()


async def test_root_balance() -> None:
    amount = Amount.ether(123)
    provider = LocalProvider(root_balance=amount)
    client = Client(provider=provider)
    async with client.session() as session:
        assert await session.get_balance(provider.root.address) == amount


async def test_auto_mine(
    provider: LocalProvider,
    session: ClientSession,
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    amount = Amount.ether(1)
    dest = another_signer.address

    # Auto-mininig is the default behavior
    tx_hash = await session.broadcast_transfer(root_signer, dest, amount)
    receipt = await session.rpc.eth_get_transaction_receipt(tx_hash)
    assert receipt is not None
    assert receipt.succeeded
    assert await session.get_balance(dest) == amount

    # Disable auto-mining. Now broadcasting the transaction does not automatically finalize it.
    provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(root_signer, dest, amount)
    receipt = await session.rpc.eth_get_transaction_receipt(tx_hash)
    assert receipt is None
    assert await session.get_balance(dest) == amount

    # Enable auto-mining back. The pending transactions are added to the block.
    provider.enable_auto_mine_transactions()
    receipt = await session.rpc.eth_get_transaction_receipt(tx_hash)
    assert receipt is not None
    assert receipt.succeeded
    assert await session.get_balance(dest) == Amount.ether(2)


async def test_snapshots(
    provider: LocalProvider,
    session: ClientSession,
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    amount = Amount.ether(1)
    double_amount = Amount.ether(2)
    dest = another_signer.address

    await session.transfer(root_signer, dest, amount)
    snapshot_id = provider.take_snapshot()
    await session.transfer(root_signer, dest, amount)
    assert await session.get_balance(dest) == double_amount

    provider.revert_to_snapshot(snapshot_id)
    assert await session.get_balance(dest) == amount


async def test_net_version(session: ClientSession) -> None:
    assert await session.net_version() == "1"


def test_rpc_error(provider: LocalProvider) -> None:
    with pytest.raises(
        ProviderError,
        match=re.escape(
            "Provider error: RPC error (RPCErrorCode.METHOD_NOT_FOUND): "
            "Unknown method: eth_nonexistentMethod"
        ),
    ):
        provider.rpc("eth_nonexistentMethod")


def test_eth_chain_id() -> None:
    provider = LocalProvider(root_balance=Amount.ether(100), chain_id=0xABC)
    assert provider.rpc("eth_chainId") == "0xabc"
