# TODO (#60): expand the tests so that this file covered 100% of the respective submodule,
# and don't use high-level API.

from pathlib import Path

import pytest

from pons import (
    AccountSigner,
    Address,
    Amount,
    Block,
    Client,
    LocalProvider,
    TxHash,
    abi,
    compile_contract_file,
)
from pons._abi_types import decode_args, encode_args
from pons._entities import (
    BlockInfo,
    TxInfo,
    rpc_decode_data,
    rpc_encode_block,
    rpc_encode_data,
    rpc_encode_quantity,
)


# Masking the global fixtures to make this test self-contained
# (since LocalProvider is what we're testing).
@pytest.fixture
def provider():
    return LocalProvider(root_balance=Amount.ether(100))


@pytest.fixture
async def session(provider):
    client = Client(provider=provider)
    async with client.session() as session:
        yield session


@pytest.fixture
def root_signer(provider):
    return provider.root


@pytest.fixture
def another_signer():
    return AccountSigner.create()


def make_transfer_tx(provider, dest, amount, nonce):
    return {
        "type": rpc_encode_quantity(2),  # EIP-2930 transaction
        "chainId": provider.rpc("eth_chainId"),
        "to": dest.rpc_encode(),
        "value": amount.rpc_encode(),
        # This is the fixed price for the transfer in Ethereum.
        # Ideally we should take it from estimate_gas(), but for tests we short-circuit it.
        "gas": rpc_encode_quantity(21000),
        "maxFeePerGas": provider.rpc("eth_gasPrice"),
        "maxPriorityFeePerGas": Amount.gwei(1).rpc_encode(),
        "nonce": rpc_encode_quantity(nonce),
    }


async def test_root_balance():
    amount = Amount.ether(123)
    provider = LocalProvider(root_balance=amount)
    client = Client(provider=provider)
    async with client.session() as session:
        assert await session.eth_get_balance(provider.root.address) == amount


async def test_auto_mine(provider, session, root_signer, another_signer):
    amount = Amount.ether(1)
    dest = another_signer.address
    latest = rpc_encode_block(Block.LATEST)

    # Auto-mininig is the default behavior
    tx_hash = await session.broadcast_transfer(root_signer, dest, amount)
    receipt = await session.eth_get_transaction_receipt(tx_hash)
    assert receipt.succeeded
    assert provider.rpc("eth_getBalance", dest.rpc_encode(), latest) == amount.rpc_encode()

    # Disable auto-mining. Now broadcasting the transaction does not automatically finalize it.
    provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(root_signer, dest, amount)
    receipt = await session.eth_get_transaction_receipt(tx_hash)
    assert receipt is None
    assert provider.rpc("eth_getBalance", dest.rpc_encode(), latest) == amount.rpc_encode()

    # Enable auto-mining back. The pending transactions are added to the block.
    provider.enable_auto_mine_transactions()
    receipt = await session.eth_get_transaction_receipt(tx_hash)
    assert receipt.succeeded
    assert provider.rpc("eth_getBalance", dest.rpc_encode(), latest) == Amount.ether(2).rpc_encode()


async def test_snapshots(provider, session, root_signer, another_signer):
    amount = Amount.ether(1)
    double_amount = Amount.ether(2)
    dest = another_signer.address
    latest = rpc_encode_block(Block.LATEST)

    await session.broadcast_transfer(root_signer, dest, amount)
    snapshot_id = provider.take_snapshot()
    await session.broadcast_transfer(root_signer, dest, amount)
    assert provider.rpc("eth_getBalance", dest.rpc_encode(), latest) == double_amount.rpc_encode()

    provider.revert_to_snapshot(snapshot_id)
    assert provider.rpc("eth_getBalance", dest.rpc_encode(), latest) == amount.rpc_encode()


def test_net_version(provider):
    assert provider.rpc("net_version") == "1"


def test_eth_chain_id():
    provider = LocalProvider(root_balance=Amount.ether(100), chain_id=0xABC)
    # Something set in the depths of PyEVM by default.
    # May be worth making it customizable at some point.
    assert provider.rpc("eth_chainId") == "0xabc"


def test_eth_get_balance():
    amount = Amount.ether(123)
    provider = LocalProvider(root_balance=amount)
    balance = provider.rpc(
        "eth_getBalance", provider.root.address.rpc_encode(), rpc_encode_block(Block.LATEST)
    )
    assert balance == rpc_encode_quantity(amount.as_wei())


async def test_eth_get_transaction_count(provider, session, root_signer, another_signer):
    address = root_signer.address.rpc_encode()
    assert provider.rpc("eth_getTransactionCount", address, rpc_encode_block(Block.LATEST)) == "0x0"
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    assert provider.rpc("eth_getTransactionCount", address, rpc_encode_block(Block.LATEST)) == "0x1"


async def test_eth_send_raw_transaction(provider, root_signer, another_signer):
    amount = Amount.ether(1)
    dest = another_signer.address
    latest = rpc_encode_block(Block.LATEST)

    tx = make_transfer_tx(provider, dest, amount, 0)
    signed_tx = root_signer.sign_transaction(tx)
    provider.rpc("eth_sendRawTransaction", rpc_encode_data(signed_tx))

    # Test that the transaction came through
    assert provider.rpc("eth_getBalance", dest.rpc_encode(), latest) == amount.rpc_encode()


async def test_eth_call(provider, session, root_signer):
    path = Path(__file__).resolve().parent / "TestLocalProvider.sol"
    compiled = compile_contract_file(path)
    compiled_contract = compiled["BasicContract"]

    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor())

    result = provider.rpc(
        "eth_call",
        {
            "to": deployed_contract.address.rpc_encode(),
            "data": rpc_encode_data(
                compiled_contract.abi.method.getState.selector + encode_args([abi.uint(256), 456])
            ),
        },
        rpc_encode_block(Block.LATEST),
    )

    assert decode_args([abi.uint(256)], rpc_decode_data(result)) == (123 + 456,)

    # Use an explicit `from` field to cover the branch where it is substituted if missing.
    result = provider.rpc(
        "eth_call",
        {
            "from": root_signer.address.rpc_encode(),
            "to": deployed_contract.address.rpc_encode(),
            "data": rpc_encode_data(
                compiled_contract.abi.method.getState.selector + encode_args([abi.uint(256), 456])
            ),
        },
        rpc_encode_block(Block.LATEST),
    )

    assert decode_args([abi.uint(256)], rpc_decode_data(result)) == (123 + 456,)


async def test_eth_block_number(provider, session, root_signer, another_signer):
    assert provider.rpc("eth_blockNumber") == "0x0"
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    assert provider.rpc("eth_blockNumber") == "0x1"


async def test_eth_get_transaction_by_hash(provider, root_signer, another_signer):
    amount = Amount.ether(1)
    dest = another_signer.address

    tx = make_transfer_tx(provider, dest, amount, 0)
    signed_tx = root_signer.sign_transaction(tx)
    tx_hash = TxHash.rpc_decode(provider.rpc("eth_sendRawTransaction", rpc_encode_data(signed_tx)))

    recorded_tx = provider.rpc("eth_getTransactionByHash", tx_hash.rpc_encode())

    preserved_fields = [
        "type",
        "chainId",
        "nonce",
        "value",
        "gas",
        "maxFeePerGas",
        "maxPriorityFeePerGas",
    ]
    for field in preserved_fields:
        assert recorded_tx[field] == tx[field]

    assert tx["to"] == Address.from_hex(recorded_tx["to"]).checksum
    assert recorded_tx["blockNumber"] == "0x1"

    # Test non-existent transaction
    assert provider.rpc("eth_getTransactionByHash", "0x" + "1" * 64) is None


async def test_eth_get_block_by_hash(provider, root_signer, another_signer):
    amount = Amount.ether(1)
    dest = another_signer.address

    tx = make_transfer_tx(provider, dest, amount, 0)
    signed_tx = root_signer.sign_transaction(tx)
    tx_hash = TxHash.rpc_decode(provider.rpc("eth_sendRawTransaction", rpc_encode_data(signed_tx)))
    recorded_tx = TxInfo.rpc_decode(provider.rpc("eth_getTransactionByHash", tx_hash.rpc_encode()))

    block = BlockInfo.rpc_decode(
        provider.rpc("eth_getBlockByHash", recorded_tx.block_hash.rpc_encode(), True)
    )
    assert block.number == 1
    assert block.miner == Address.from_hex("0x0000000000000000000000000000000000000000")
