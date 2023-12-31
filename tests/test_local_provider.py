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
from pons._provider import RPCError, RPCErrorCode


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
        "chainId": provider.eth_chain_id(),
        "to": dest.rpc_encode(),
        "value": amount.rpc_encode(),
        # This is the fixed price for the transfer in Ethereum.
        # Ideally we should take it from estimate_gas(), but for tests we short-circuit it.
        "gas": rpc_encode_quantity(21000),
        "maxFeePerGas": provider.eth_gas_price(),
        "maxPriorityFeePerGas": Amount.gwei(1).rpc_encode(),
        "nonce": rpc_encode_quantity(nonce),
    }


async def test_method_not_found(provider):
    with pytest.raises(RPCError) as excinfo:
        provider.rpc("unknown_method", 1, 2)
    assert excinfo.value.code == RPCErrorCode.METHOD_NOT_FOUND.value
    assert excinfo.value.message == "The method unknown_method does not exist/is not available"


async def test_invalid_parameter(provider):
    with pytest.raises(RPCError) as excinfo:
        provider.rpc("eth_getBalance", 1)  # one missing argument
    assert excinfo.value.code == RPCErrorCode.INVALID_PARAMETER.value


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
    assert provider.eth_get_balance(dest.rpc_encode(), latest) == amount.rpc_encode()

    # Disable auto-mining. Now broadcasting the transaction does not automatically finalize it.
    provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(root_signer, dest, amount)
    receipt = await session.eth_get_transaction_receipt(tx_hash)
    assert receipt is None
    assert provider.eth_get_balance(dest.rpc_encode(), latest) == amount.rpc_encode()

    # Enable auto-mining back. The pending transactions are added to the block.
    provider.enable_auto_mine_transactions()
    receipt = await session.eth_get_transaction_receipt(tx_hash)
    assert receipt.succeeded
    assert provider.eth_get_balance(dest.rpc_encode(), latest) == Amount.ether(2).rpc_encode()


def test_net_version(provider):
    assert provider.net_version() == "0"


def test_eth_chain_id(provider):
    # Something set in the depths of PyEVM by default.
    # May be worth making it customizable at some point.
    assert provider.eth_chain_id() == "0x776562337079"


def test_eth_get_balance():
    amount = Amount.ether(123)
    provider = LocalProvider(root_balance=amount)
    balance = provider.eth_get_balance(
        provider.root.address.rpc_encode(), rpc_encode_block(Block.LATEST)
    )
    assert balance == rpc_encode_quantity(amount.as_wei())


async def test_eth_get_transaction_count(provider, session, root_signer, another_signer):
    address = root_signer.address.rpc_encode()
    assert provider.eth_get_transaction_count(address, rpc_encode_block(Block.LATEST)) == "0x0"
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    assert provider.eth_get_transaction_count(address, rpc_encode_block(Block.LATEST)) == "0x1"


async def test_eth_send_raw_transaction(provider, root_signer, another_signer):
    amount = Amount.ether(1)
    dest = another_signer.address
    latest = rpc_encode_block(Block.LATEST)

    tx = make_transfer_tx(provider, dest, amount, 0)
    signed_tx = root_signer.sign_transaction(tx)
    provider.eth_send_raw_transaction(rpc_encode_data(signed_tx))

    # Test that the transaction came through
    assert provider.eth_get_balance(dest.rpc_encode(), latest) == amount.rpc_encode()


async def test_eth_call(provider, session, root_signer):
    path = Path(__file__).resolve().parent / "TestLocalProvider.sol"
    compiled = compile_contract_file(path)
    compiled_contract = compiled["BasicContract"]

    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor())

    result = provider.eth_call(
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
    result = provider.eth_call(
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
    assert provider.eth_block_number() == "0x0"
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    assert provider.eth_block_number() == "0x1"


async def test_eth_get_transaction_by_hash(provider, root_signer, another_signer):
    amount = Amount.ether(1)
    dest = another_signer.address

    tx = make_transfer_tx(provider, dest, amount, 0)
    signed_tx = root_signer.sign_transaction(tx)
    tx_hash = TxHash.rpc_decode(provider.eth_send_raw_transaction(rpc_encode_data(signed_tx)))

    recorded_tx = provider.eth_get_transaction_by_hash(tx_hash.rpc_encode())

    preserved_fields = [
        "type",
        "chainId",
        "nonce",
        "value",
        "to",
        "gas",
        "maxFeePerGas",
        "maxPriorityFeePerGas",
    ]
    for field in preserved_fields:
        assert recorded_tx[field] == tx[field]

    assert recorded_tx["blockNumber"] == "0x1"

    # Test non-existent transaction
    assert provider.eth_get_transaction_by_hash("0x" + "1" * 64) is None


async def test_eth_get_block_by_hash(provider, root_signer, another_signer):
    amount = Amount.ether(1)
    dest = another_signer.address

    tx = make_transfer_tx(provider, dest, amount, 0)
    signed_tx = root_signer.sign_transaction(tx)
    tx_hash = TxHash.rpc_decode(provider.eth_send_raw_transaction(rpc_encode_data(signed_tx)))
    recorded_tx = TxInfo.rpc_decode(provider.eth_get_transaction_by_hash(tx_hash.rpc_encode()))

    block = BlockInfo.rpc_decode(
        provider.eth_get_block_by_hash(recorded_tx.block_hash.rpc_encode(), with_transactions=True)
    )
    assert block.number == 1
    assert block.miner == Address.from_hex("0x0000000000000000000000000000000000000000")
