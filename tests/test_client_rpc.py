import os
import re
from collections.abc import Awaitable, Iterable
from pathlib import Path
from typing import Any

import pytest
from ethereum_rpc import (
    Address,
    Amount,
    BlockHash,
    BlockLabel,
    ErrorCode,
    LogEntry,
    LogTopic,
    RPCError,
    RPCErrorCode,
    TxHash,
    TxInfo,
    keccak,
)

from pons import (
    AccountSigner,
    BadResponseFormat,
    ClientSession,
    CompiledContract,
    Either,
    ProviderError,
    abi,
)
from pons._abi_types import encode_args
from pons._provider import RPC_JSON
from pons.compiler import compile_contract_file
from pons.local_provider import LocalProvider


@pytest.fixture
def compiled_contracts() -> dict[str, CompiledContract]:
    path = Path(__file__).resolve().parent / "TestClient.sol"
    return compile_contract_file(path)


def normalize_topics(topics: Iterable[LogTopic]) -> tuple[tuple[LogTopic], ...]:
    """
    Reduces visual noise in assertions by bringing the log topics in a log entry
    (a tuple of single elements) to the format used in EventFilter
    (where even single elements are 1-tuples).
    """
    return tuple((elem,) for elem in topics)


async def test_eth_get_balance(
    session: ClientSession, root_signer: AccountSigner, another_signer: AccountSigner
) -> None:
    to_transfer = Amount.ether(10)
    await session.transfer(root_signer, another_signer.address, to_transfer)
    acc1_balance = await session.rpc.eth_get_balance(another_signer.address)
    assert acc1_balance == to_transfer

    # Non-existent address (which is technically just an unfunded address)
    random_addr = Address(os.urandom(20))
    balance = await session.rpc.eth_get_balance(random_addr)
    assert balance == Amount.ether(0)


async def test_eth_get_transaction_receipt(
    local_provider: LocalProvider,
    session: ClientSession,
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    local_provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(
        root_signer, another_signer.address, Amount.ether(10)
    )
    receipt = await session.rpc.eth_get_transaction_receipt(tx_hash)
    assert receipt is None

    local_provider.enable_auto_mine_transactions()
    receipt = await session.rpc.eth_get_transaction_receipt(tx_hash)
    assert receipt is not None
    assert receipt.succeeded

    # A non-existent transaction
    receipt = await session.rpc.eth_get_transaction_receipt(TxHash(os.urandom(32)))
    assert receipt is None


async def test_eth_get_transaction_count(
    local_provider: LocalProvider,
    session: ClientSession,
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    assert await session.rpc.eth_get_transaction_count(root_signer.address) == 0
    await session.transfer(root_signer, another_signer.address, Amount.ether(10))
    assert await session.rpc.eth_get_transaction_count(root_signer.address) == 1

    # Check that pending transactions are accounted for
    local_provider.disable_auto_mine_transactions()
    await session.broadcast_transfer(root_signer, another_signer.address, Amount.ether(10))
    assert await session.rpc.eth_get_transaction_count(root_signer.address, BlockLabel.PENDING) == 2


async def test_eth_gas_price(session: ClientSession) -> None:
    gas_price = await session.rpc.eth_gas_price()
    assert isinstance(gas_price, Amount)


async def test_eth_block_number(
    session: ClientSession, root_signer: AccountSigner, another_signer: AccountSigner
) -> None:
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    await session.transfer(root_signer, another_signer.address, Amount.ether(2))
    await session.transfer(root_signer, another_signer.address, Amount.ether(3))
    block_num = await session.rpc.eth_block_number()

    block_info = await session.rpc.eth_get_block_by_number(block_num - 1, with_transactions=True)
    assert block_info is not None
    assert isinstance(block_info.transactions[0], TxInfo)
    assert block_info.transactions[0].value == Amount.ether(2)


async def test_eth_get_block(
    session: ClientSession, root_signer: AccountSigner, another_signer: AccountSigner
) -> None:
    to_transfer = Amount.ether(10)
    await session.transfer(root_signer, another_signer.address, to_transfer)

    block_info = await session.rpc.eth_get_block_by_number(1, with_transactions=True)
    assert block_info is not None
    assert all(isinstance(tx, TxInfo) for tx in block_info.transactions)

    assert block_info.hash_ is not None
    block_info2 = await session.rpc.eth_get_block_by_hash(block_info.hash_, with_transactions=True)
    assert block_info2 == block_info

    # no transactions
    block_info = await session.rpc.eth_get_block_by_number(1)
    assert block_info is not None
    assert all(isinstance(tx, TxHash) for tx in block_info.transactions)

    # non-existent block
    block_info = await session.rpc.eth_get_block_by_number(100, with_transactions=True)
    assert block_info is None
    block_info = await session.rpc.eth_get_block_by_hash(
        BlockHash(b"\x00" * 32), with_transactions=True
    )
    assert block_info is None


async def test_eth_get_block_pending(
    local_provider: LocalProvider,
    session: ClientSession,
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))

    local_provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(
        root_signer, another_signer.address, Amount.ether(10)
    )

    block_info = await session.rpc.eth_get_block_by_number(
        BlockLabel.PENDING, with_transactions=True
    )
    assert block_info is not None
    assert block_info.number == 2
    assert block_info.hash_ is None
    assert block_info.nonce is None
    assert block_info.miner is None
    assert block_info.total_difficulty is None
    assert len(block_info.transactions) == 1
    assert isinstance(block_info.transactions[0], TxInfo)
    assert block_info.transactions[0].hash_ == tx_hash
    assert block_info.transactions[0].value == Amount.ether(10)

    block_info = await session.rpc.eth_get_block_by_number(
        BlockLabel.PENDING, with_transactions=False
    )
    assert block_info is not None
    assert len(block_info.transactions) == 1
    assert block_info.transactions[0] == tx_hash


async def test_eth_get_transaction_by_hash(
    local_provider: LocalProvider,
    session: ClientSession,
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    to_transfer = Amount.ether(1)

    tx_hash = await session.broadcast_transfer(root_signer, another_signer.address, to_transfer)
    tx_info = await session.rpc.eth_get_transaction_by_hash(tx_hash)
    assert tx_info is not None
    assert tx_info.value == to_transfer

    non_existent = TxHash(b"abcd" * 8)
    tx_info = await session.rpc.eth_get_transaction_by_hash(non_existent)
    assert tx_info is None

    local_provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(root_signer, another_signer.address, to_transfer)
    tx_info = await session.rpc.eth_get_transaction_by_hash(tx_hash)

    assert tx_info is not None
    assert tx_info.block_number == 2
    assert tx_info.block_hash is None
    assert tx_info.transaction_index is None
    assert tx_info.value == to_transfer


async def test_eth_get_code(
    session: ClientSession,
    root_signer: AccountSigner,
    compiled_contracts: dict[str, CompiledContract],
) -> None:
    compiled_contract = compiled_contracts["EmptyContract"]
    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor(123))
    bytecode = await session.rpc.eth_get_code(deployed_contract.address, block=BlockLabel.LATEST)

    # The bytecode being deployed is not the code that will be stored on chain,
    # but some code that, having been executed, returns the code that will be stored on chain.
    # So all we can do is check that the code stored on chain is a part of the initialization code.
    assert bytecode in compiled_contract.bytecode


async def test_eth_get_storage_at(
    session: ClientSession,
    root_signer: AccountSigner,
    compiled_contracts: dict[str, CompiledContract],
) -> None:
    x = 0xAB
    y_key = Address(os.urandom(20))
    y_val = 0xCD

    compiled_contract = compiled_contracts["Storage"]
    deployed_contract = await session.deploy(
        root_signer, compiled_contract.constructor(x, y_key, y_val)
    )

    # Get the regular stored value
    storage = await session.rpc.eth_get_storage_at(
        deployed_contract.address, 0, block=BlockLabel.LATEST
    )
    assert storage == b"\x00" * 31 + x.to_bytes(1, byteorder="big")

    # Get the value of the mapping
    position = int.from_bytes(
        keccak(
            # left-padded key
            b"\x00" * 12
            + bytes(y_key)
            # left-padded position of the mapping (1)
            + b"\x00" * 31
            + b"\x01"
        ),
        byteorder="big",
    )
    storage = await session.rpc.eth_get_storage_at(
        deployed_contract.address, position, block=BlockLabel.LATEST
    )
    assert storage == b"\x00" * 31 + y_val.to_bytes(1, byteorder="big")


async def test_eth_call(
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    compiled_contract = compiled_contracts["BasicContract"]
    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor(123))
    result = await session.call(deployed_contract.method.getState(456))
    assert result == 123 + 456

    # With a real provider, if `sender_address` is not given, it will default to the zero address.
    result = await session.call(deployed_contract.method.getSender())
    assert result == Address(b"\x00" * 20)

    # Seems to be another tester chain limitation: even though `eth_call` does not spend gas,
    # the `sender_address` still needs to be funded.
    await session.transfer(root_signer, another_signer.address, Amount.ether(10))

    result = await session.call(
        deployed_contract.method.getSender(), sender_address=another_signer.address
    )
    assert result == another_signer.address


async def test_eth_call_pending(
    local_provider: LocalProvider,
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
) -> None:
    compiled_contract = compiled_contracts["BasicContract"]
    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor(123))

    local_provider.disable_auto_mine_transactions()
    await session.broadcast_transact(root_signer, deployed_contract.method.setState(456))

    # This uses the state of the last finalized block
    result = await session.call(deployed_contract.method.getState(0))
    assert result == 123

    # This also uses the state change introduced by the pending transaction
    result = await session.call(deployed_contract.method.getState(0), block=BlockLabel.PENDING)
    assert result == 456


async def test_eth_get_filter_changes_bad_response(
    local_provider: LocalProvider, session: ClientSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    block_filter = await session.rpc.eth_new_block_filter()

    def mock_rpc(_method: str, *_args: Any) -> RPC_JSON:
        return {"foo": 1}

    monkeypatch.setattr(local_provider, "rpc", mock_rpc)

    with pytest.raises(
        BadResponseFormat,
        match=r"eth_getFilterChanges: Can only structure a tuple or a list into a tuple generic",
    ):
        await session.rpc.eth_get_filter_changes(block_filter)


async def test_block_filter(
    session: ClientSession, root_signer: AccountSigner, another_signer: AccountSigner
) -> None:
    to_transfer = Amount.ether(1)

    await session.transfer(root_signer, another_signer.address, to_transfer)

    block_filter = await session.rpc.eth_new_block_filter()

    await session.transfer(root_signer, another_signer.address, to_transfer)
    await session.transfer(root_signer, another_signer.address, to_transfer)

    last_block = await session.rpc.eth_get_block_by_number(BlockLabel.LATEST)
    assert last_block is not None
    prev_block = await session.rpc.eth_get_block_by_number(last_block.number - 1)
    assert prev_block is not None

    block_hashes = await session.rpc.eth_get_filter_changes(block_filter)
    assert block_hashes == (prev_block.hash_, last_block.hash_)

    await session.transfer(root_signer, another_signer.address, to_transfer)

    block_hashes = await session.rpc.eth_get_filter_changes(block_filter)
    last_block = await session.rpc.eth_get_block_by_number(BlockLabel.LATEST)
    assert last_block is not None
    assert block_hashes == (last_block.hash_,)

    block_hashes = await session.rpc.eth_get_filter_changes(block_filter)
    assert len(block_hashes) == 0


async def test_pending_transaction_filter(
    local_provider: LocalProvider,
    session: ClientSession,
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    transaction_filter = await session.rpc.eth_new_pending_transaction_filter()

    to_transfer = Amount.ether(1)

    local_provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(root_signer, another_signer.address, to_transfer)
    tx_hashes = await session.rpc.eth_get_filter_changes(transaction_filter)
    assert tx_hashes == (tx_hash,)


async def test_eth_get_logs(
    monkeypatch: pytest.MonkeyPatch,
    local_provider: LocalProvider,
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))
    await session.transact(root_signer, contract1.method.deposit(b"1234"))
    await session.transact(another_signer, contract2.method.deposit2(b"4567"))

    entries = await session.rpc.eth_get_logs(source=contract2.address)
    assert len(entries) == 1
    assert entries[0].address == contract2.address
    assert (
        normalize_topics(entries[0].topics)
        == contract2.abi.event.Deposit2(another_signer.address, b"4567").topics
    )

    entries = await session.rpc.eth_get_logs(
        source=[contract1.address, contract2.address], from_block=0
    )
    assert len(entries) == 2
    assert entries[0].address == contract1.address
    assert entries[1].address == contract2.address
    assert (
        normalize_topics(entries[0].topics)
        == contract1.abi.event.Deposit(root_signer.address, b"1234").topics
    )
    assert (
        normalize_topics(entries[1].topics)
        == contract2.abi.event.Deposit2(another_signer.address, b"4567").topics
    )

    # Test an invalid response

    def mock_rpc(_method: str, *_args: Any) -> RPC_JSON:
        return {"foo": 1}

    monkeypatch.setattr(local_provider, "rpc", mock_rpc)

    with pytest.raises(
        BadResponseFormat,
        match=r"eth_getLogs: Can only structure a tuple or a list into a tuple generic",
    ):
        await session.rpc.eth_get_logs(source=contract2.address)


async def test_eth_get_filter_logs(
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))

    log_filter = await session.rpc.eth_new_filter()
    await session.transact(root_signer, contract1.method.deposit(b"1234"))
    await session.transact(another_signer, contract2.method.deposit2(b"4567"))

    entries = await session.rpc.eth_get_filter_logs(log_filter)
    assert len(entries) == 2
    assert isinstance(entries[0], LogEntry)
    assert isinstance(entries[1], LogEntry)
    assert entries[0].address == contract1.address
    assert entries[1].address == contract2.address

    assert (
        normalize_topics(entries[0].topics)
        == contract1.abi.event.Deposit(root_signer.address, b"1234").topics
    )
    assert (
        normalize_topics(entries[1].topics)
        == contract2.abi.event.Deposit2(another_signer.address, b"4567").topics
    )


async def test_log_filter_all(
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))

    log_filter = await session.rpc.eth_new_filter()
    await session.transact(root_signer, contract1.method.deposit(b"1234"))
    await session.transact(another_signer, contract2.method.deposit2(b"4567"))

    entries = await session.rpc.eth_get_filter_changes(log_filter)
    assert len(entries) == 2
    assert isinstance(entries[0], LogEntry)
    assert isinstance(entries[1], LogEntry)
    assert entries[0].address == contract1.address
    assert entries[1].address == contract2.address

    assert (
        normalize_topics(entries[0].topics)
        == contract1.abi.event.Deposit(root_signer.address, b"1234").topics
    )
    assert (
        normalize_topics(entries[1].topics)
        == contract2.abi.event.Deposit2(another_signer.address, b"4567").topics
    )


async def test_log_filter_by_address(
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))

    # Filter by a single address

    log_filter = await session.rpc.eth_new_filter(source=contract2.address)
    await session.transact(root_signer, contract1.method.deposit(b"1234"))
    await session.transact(root_signer, contract2.method.deposit2(b"4567"))

    entries = await session.rpc.eth_get_filter_changes(log_filter)
    assert len(entries) == 1
    assert isinstance(entries[0], LogEntry)
    assert entries[0].address == contract2.address
    assert (
        normalize_topics(entries[0].topics)
        == contract2.abi.event.Deposit2(root_signer.address, b"4567").topics
    )

    # Filter by several addresses

    contract3 = await session.deploy(another_signer, basic_contract.constructor(123))

    log_filter = await session.rpc.eth_new_filter(source=[contract1.address, contract3.address])
    await session.transact(root_signer, contract1.method.deposit(b"1111"))
    await session.transact(root_signer, contract2.method.deposit(b"2222"))
    await session.transact(root_signer, contract3.method.deposit(b"3333"))

    entries = await session.rpc.eth_get_filter_changes(log_filter)
    assert len(entries) == 2
    assert isinstance(entries[0], LogEntry)
    assert isinstance(entries[1], LogEntry)
    assert entries[0].address == contract1.address
    assert (
        normalize_topics(entries[0].topics)
        == contract1.abi.event.Deposit(root_signer.address, b"1111").topics
    )
    assert entries[1].address == contract3.address
    assert (
        normalize_topics(entries[1].topics)
        == contract3.abi.event.Deposit(root_signer.address, b"3333").topics
    )


async def test_log_filter_by_topic(
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))

    # Filter by a specific topic or None at each position

    log_filter = await session.rpc.eth_new_filter(
        event_filter=contract2.abi.event.Deposit2(id=b"4567")
    )
    # filtered out, wrong event type
    await session.transact(root_signer, contract1.method.deposit(b"4567"))
    # matches the filter
    await session.transact(root_signer, contract1.method.deposit2(b"4567"))
    # filtered out, wrong value
    await session.transact(another_signer, contract2.method.deposit2(b"7890"))
    # matches the filter
    await session.transact(another_signer, contract2.method.deposit2(b"4567"))

    entries = await session.rpc.eth_get_filter_changes(log_filter)
    assert len(entries) == 2
    assert isinstance(entries[0], LogEntry)
    assert isinstance(entries[1], LogEntry)
    assert entries[0].address == contract1.address
    assert (
        normalize_topics(entries[0].topics)
        == contract1.abi.event.Deposit2(root_signer.address, b"4567").topics
    )
    assert entries[1].address == contract2.address
    assert (
        normalize_topics(entries[1].topics)
        == contract2.abi.event.Deposit2(another_signer.address, b"4567").topics
    )

    # Filter by a list of topics

    event_filter = contract1.abi.event.Deposit(id=Either(b"1111", b"3333"))
    log_filter = await session.rpc.eth_new_filter(event_filter=event_filter)
    await session.transact(root_signer, contract1.method.deposit(b"1111"))
    await session.transact(root_signer, contract1.method.deposit2(b"1111"))  # filtered out
    await session.transact(root_signer, contract1.method.deposit(b"2222"))  # filtered out
    await session.transact(another_signer, contract2.method.deposit(b"3333"))

    entries = await session.rpc.eth_get_filter_changes(log_filter)
    assert len(entries) == 2
    assert isinstance(entries[0], LogEntry)
    assert isinstance(entries[1], LogEntry)
    assert entries[0].address == contract1.address
    assert (
        normalize_topics(entries[0].topics)
        == contract1.abi.event.Deposit(root_signer.address, b"1111").topics
    )
    assert entries[1].address == contract2.address
    assert (
        normalize_topics(entries[1].topics)
        == contract2.abi.event.Deposit(another_signer.address, b"3333").topics
    )


async def test_log_filter_by_block_num(
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))

    await session.transact(root_signer, contract1.method.deposit(b"1111"))
    block_num = await session.rpc.eth_block_number()
    log_filter = await session.rpc.eth_new_filter(from_block=block_num + 1, to_block=block_num + 3)

    await session.transact(root_signer, contract1.method.deposit(b"2222"))  # filter will start here
    await session.transact(root_signer, contract1.method.deposit(b"3333"))
    await session.transact(root_signer, contract1.method.deposit(b"4444"))  # filter will stop here
    await session.transact(root_signer, contract1.method.deposit(b"5555"))

    entries = await session.rpc.eth_get_filter_changes(log_filter)

    # The range in the filter is inclusive
    for i, entry in enumerate(entries):
        assert isinstance(entry, LogEntry)
        assert entry.block_number == block_num + i + 1
        assert (
            normalize_topics(entry.topics)
            == contract1.abi.event.Deposit(root_signer.address, (str(i + 2) * 4).encode()).topics
        )


async def test_unknown_rpc_status_code(
    local_provider: LocalProvider, session: ClientSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def mock_rpc(_method: str, *_args: Any) -> RPC_JSON:
        # This is a known exception type, and it will be transferred through the network
        # keeping the status code.
        raise RPCError(ErrorCode(666), "this method is possessed")

    monkeypatch.setattr(local_provider, "rpc", mock_rpc)

    with pytest.raises(RPCError, match=re.escape("RPC error (666): this method is possessed")):
        await session.net_version()


async def check_rpc_error(
    awaitable: Awaitable[Any],
    expected_code: RPCErrorCode | None,
    expected_message: str,
    expected_data: bytes | None,
) -> None:
    with pytest.raises(ProviderError) as exc:
        await awaitable

    assert isinstance(exc.value.error, RPCError)
    assert exc.value.error.parsed_code == expected_code
    assert exc.value.error.message == expected_message
    assert exc.value.error.data == expected_data


async def test_contract_exceptions(
    session: ClientSession,
    root_signer: AccountSigner,
    compiled_contracts: dict[str, CompiledContract],
) -> None:
    compiled_contract = compiled_contracts["TestErrors"]
    contract = await session.deploy(root_signer, compiled_contract.constructor(999))

    error_selector = keccak(b"Error(string)")[:4]
    custom_error_selector = keccak(b"CustomError(uint256)")[:4]

    # `require(condition)`
    await check_rpc_error(
        session.rpc.eth_call(contract.method.viewError(0)),
        expected_code=RPCErrorCode.SERVER_ERROR,
        expected_message="execution reverted",
        expected_data=None,
    )

    # `require(condition, message)`
    await check_rpc_error(
        session.rpc.eth_call(contract.method.viewError(1)),
        expected_code=RPCErrorCode.EXECUTION_ERROR,
        expected_message="execution reverted",
        expected_data=error_selector + encode_args((abi.string, "require(string)")),
    )

    # `revert()`
    await check_rpc_error(
        session.rpc.eth_call(contract.method.viewError(2)),
        expected_code=RPCErrorCode.SERVER_ERROR,
        expected_message="execution reverted",
        expected_data=None,
    )

    # `revert(message)`
    await check_rpc_error(
        session.rpc.eth_call(contract.method.viewError(3)),
        expected_code=RPCErrorCode.EXECUTION_ERROR,
        expected_message="execution reverted",
        expected_data=error_selector + encode_args((abi.string, "revert(string)")),
    )

    # `revert CustomError(...)`
    await check_rpc_error(
        session.rpc.eth_call(contract.method.viewError(4)),
        expected_code=RPCErrorCode.EXECUTION_ERROR,
        expected_message="execution reverted",
        expected_data=custom_error_selector + encode_args((abi.uint(256), 4)),
    )


async def test_contract_panics(
    session: ClientSession,
    root_signer: AccountSigner,
    compiled_contracts: dict[str, CompiledContract],
) -> None:
    compiled_contract = compiled_contracts["TestErrors"]
    contract = await session.deploy(root_signer, compiled_contract.constructor(999))

    panic_selector = keccak(b"Panic(uint256)")[:4]

    await check_rpc_error(
        session.rpc.eth_call(contract.method.viewPanic(0)),
        expected_code=RPCErrorCode.EXECUTION_ERROR,
        expected_message="execution reverted",
        expected_data=panic_selector + encode_args((abi.uint(256), 0x01)),
    )

    await check_rpc_error(
        session.rpc.eth_call(contract.method.viewPanic(1)),
        expected_code=RPCErrorCode.EXECUTION_ERROR,
        expected_message="execution reverted",
        expected_data=panic_selector + encode_args((abi.uint(256), 0x11)),
    )


async def test_eth_uninstall_filter(session: ClientSession) -> None:
    block_filter = await session.rpc.eth_new_block_filter()
    assert await session.rpc.eth_uninstall_filter(block_filter)
    # no such filter anymore
    assert not await session.rpc.eth_uninstall_filter(block_filter)
