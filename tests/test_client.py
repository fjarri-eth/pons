import os
import re
from contextlib import contextmanager
from pathlib import Path

import pytest
import trio
from ethereum_rpc import (
    Address,
    Amount,
    BlockHash,
    BlockLabel,
    RPCError,
    RPCErrorCode,
    TxHash,
    TxInfo,
    keccak,
)

from pons import (
    ABIDecodingError,
    Client,
    ContractABI,
    ContractError,
    ContractLegacyError,
    ContractPanic,
    DeployedContract,
    Either,
    LocalProvider,
    Method,
    Mutability,
    abi,
    compile_contract_file,
)
from pons._abi_types import encode_args
from pons._client import BadResponseFormat, ProviderError, TransactionFailed
from pons._contract_abi import PANIC_ERROR


@pytest.fixture
def compiled_contracts():
    path = Path(__file__).resolve().parent / "TestClient.sol"
    return compile_contract_file(path)


@contextmanager
def monkeypatched(obj, attr, patch):
    original_value = getattr(obj, attr)
    setattr(obj, attr, patch)
    yield obj
    setattr(obj, attr, original_value)


def normalize_topics(topics):
    """
    Reduces visual noise in assertions by bringing the log topics in a log entry
    (a tuple of single elements) to the format used in EventFilter
    (where even single elements are 1-tuples).
    """
    return tuple((elem,) for elem in topics)


async def test_net_version(local_provider, session):
    net_version1 = await session.net_version()
    assert net_version1 == "1"

    # This is not going to get called
    def mock_rpc(*_args):
        raise NotImplementedError  # pragma: no cover

    # The result should have been cached the first time
    with monkeypatched(local_provider, "rpc", mock_rpc):
        net_version2 = await session.net_version()
    assert net_version1 == net_version2


async def test_net_version_type_check(local_provider, session):
    # Provider returning a bad value
    with monkeypatched(local_provider, "rpc", lambda *_args: 0):
        with pytest.raises(BadResponseFormat, match="net_version: The value must be a string"):
            await session.net_version()


async def test_eth_chain_id():
    local_provider = LocalProvider(root_balance=Amount.ether(100), chain_id=123)
    client = Client(local_provider)

    # This is not going to get called
    def mock_rpc(_method, *_args):
        raise NotImplementedError  # pragma: no cover

    async with client.session() as session:
        chain_id1 = await session.eth_chain_id()
        assert chain_id1 == 123

        # The result should have been cached the first time
        with monkeypatched(local_provider, "rpc", mock_rpc):
            chain_id2 = await session.eth_chain_id()
        assert chain_id1 == chain_id2


async def test_eth_get_balance(session, root_signer, another_signer):
    to_transfer = Amount.ether(10)
    await session.transfer(root_signer, another_signer.address, to_transfer)
    acc1_balance = await session.eth_get_balance(another_signer.address)
    assert acc1_balance == to_transfer

    # Non-existent address (which is technically just an unfunded address)
    random_addr = Address(os.urandom(20))
    balance = await session.eth_get_balance(random_addr)
    assert balance == Amount.ether(0)


async def test_eth_get_transaction_receipt(local_provider, session, root_signer, another_signer):
    local_provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(
        root_signer, another_signer.address, Amount.ether(10)
    )
    receipt = await session.eth_get_transaction_receipt(tx_hash)
    assert receipt is None

    local_provider.enable_auto_mine_transactions()
    receipt = await session.eth_get_transaction_receipt(tx_hash)
    assert receipt.succeeded

    # A non-existent transaction
    receipt = await session.eth_get_transaction_receipt(TxHash(os.urandom(32)))
    assert receipt is None


async def test_eth_get_transaction_count(local_provider, session, root_signer, another_signer):
    assert await session.eth_get_transaction_count(root_signer.address) == 0
    await session.transfer(root_signer, another_signer.address, Amount.ether(10))
    assert await session.eth_get_transaction_count(root_signer.address) == 1

    # Check that pending transactions are accounted for
    local_provider.disable_auto_mine_transactions()
    await session.broadcast_transfer(root_signer, another_signer.address, Amount.ether(10))
    assert await session.eth_get_transaction_count(root_signer.address, BlockLabel.PENDING) == 2


async def test_wait_for_transaction_receipt(
    autojump_clock,  # noqa: ARG001
    local_provider,
    session,
    root_signer,
    another_signer,
):
    to_transfer = Amount.ether(10)
    local_provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(root_signer, another_signer.address, to_transfer)

    # The receipt won't be available until we mine, so the waiting should time out
    timeout = 5
    start_time = trio.current_time()
    with pytest.raises(trio.TooSlowError):
        with trio.fail_after(timeout):
            receipt = await session.wait_for_transaction_receipt(tx_hash)
    end_time = trio.current_time()
    assert end_time - start_time == timeout

    # Now let's enable mining while we wait for the receipt
    receipt = None

    async def get_receipt():
        nonlocal receipt
        receipt = await session.wait_for_transaction_receipt(tx_hash)

    async def delayed_enable_mining():
        await trio.sleep(timeout)
        local_provider.enable_auto_mine_transactions()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(get_receipt)
        nursery.start_soon(delayed_enable_mining)

    assert receipt.succeeded


async def test_eth_call(session, compiled_contracts, root_signer, another_signer):
    compiled_contract = compiled_contracts["BasicContract"]
    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor(123))
    result = await session.eth_call(deployed_contract.method.getState(456))
    assert result == (123 + 456,)

    # With a real provider, if `sender_address` is not given, it will default to the zero address.
    result = await session.eth_call(deployed_contract.method.getSender())
    assert result == (Address(b"\x00" * 20),)

    # Seems to be another tester chain limitation: even though `eth_call` does not spend gas,
    # the `sender_address` still needs to be funded.
    await session.transfer(root_signer, another_signer.address, Amount.ether(10))

    result = await session.eth_call(
        deployed_contract.method.getSender(), sender_address=another_signer.address
    )
    assert result == (another_signer.address,)


async def test_eth_call_pending(local_provider, session, compiled_contracts, root_signer):
    compiled_contract = compiled_contracts["BasicContract"]
    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor(123))

    local_provider.disable_auto_mine_transactions()
    await session.broadcast_transact(root_signer, deployed_contract.method.setState(456))

    # This uses the state of the last finalized block
    result = await session.eth_call(deployed_contract.method.getState(0))
    assert result == (123,)

    # This also uses the state change introduced by the pending transaction
    result = await session.eth_call(deployed_contract.method.getState(0), block=BlockLabel.PENDING)
    assert result == (456,)


async def test_eth_call_decoding_error(session, compiled_contracts, root_signer):
    """
    Tests that `eth_call()` propagates an error on mismatch of the declared output signature
    and the bytestring received from the provider (as opposed to wrapping it in another exception).
    """
    compiled_contract = compiled_contracts["BasicContract"]
    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor(123))

    wrong_abi = ContractABI(
        methods=[
            Method(
                name="getState",
                mutability=Mutability.VIEW,
                inputs=[abi.uint(256)],
                # the actual method in in BasicContract returns only one uint256
                outputs=[abi.uint(256), abi.uint(256)],
            )
        ]
    )
    wrong_contract = DeployedContract(abi=wrong_abi, address=deployed_contract.address)

    expected_message = (
        r"Could not decode the return value with the expected signature \(uint256,uint256\): "
        r"Tried to read 32 bytes, only got 0 bytes"
    )

    with pytest.raises(ABIDecodingError, match=expected_message):
        await session.eth_call(wrong_contract.method.getState(456))


async def test_estimate_deploy(session, compiled_contracts, root_signer):
    compiled_contract = compiled_contracts["BasicContract"]
    gas = await session.estimate_deploy(root_signer.address, compiled_contract.constructor(1))
    assert isinstance(gas, int)
    assert gas > 0


async def test_estimate_transfer(session, root_signer, another_signer):
    gas = await session.estimate_transfer(
        root_signer.address, another_signer.address, Amount.ether(10)
    )
    assert isinstance(gas, int)
    assert gas > 0

    with pytest.raises(
        ProviderError,
        match="Sender does not have enough balance to cover transaction value and gas",
    ):
        await session.estimate_transfer(
            root_signer.address, another_signer.address, Amount.ether(1000)
        )


async def test_estimate_transact(session, compiled_contracts, root_signer):
    compiled_contract = compiled_contracts["BasicContract"]
    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor(1))
    gas = await session.estimate_transact(
        root_signer.address, deployed_contract.method.setState(456)
    )
    assert isinstance(gas, int)
    assert gas > 0


async def test_eth_gas_price(session):
    gas_price = await session.eth_gas_price()
    assert isinstance(gas_price, Amount)


async def test_eth_block_number(session, root_signer, another_signer):
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    await session.transfer(root_signer, another_signer.address, Amount.ether(2))
    await session.transfer(root_signer, another_signer.address, Amount.ether(3))
    block_num = await session.eth_block_number()

    block_info = await session.eth_get_block_by_number(block_num - 1, with_transactions=True)
    assert block_info.transactions[0].value == Amount.ether(2)


async def test_transfer(session, root_signer, another_signer):
    # Regular transfer
    root_balance = await session.eth_get_balance(root_signer.address)
    to_transfer = Amount.ether(10)
    await session.transfer(root_signer, another_signer.address, to_transfer)
    root_balance_after = await session.eth_get_balance(root_signer.address)
    acc1_balance_after = await session.eth_get_balance(another_signer.address)
    assert acc1_balance_after == to_transfer
    assert root_balance - root_balance_after > to_transfer


async def test_transfer_custom_gas(session, root_signer, another_signer):
    root_balance = await session.eth_get_balance(root_signer.address)
    to_transfer = Amount.ether(10)

    # Override gas estimate
    # The standard transfer gas cost is 21000, we're being cautious here.
    await session.transfer(root_signer, another_signer.address, to_transfer, gas=22000)
    root_balance_after = await session.eth_get_balance(root_signer.address)
    acc1_balance_after = await session.eth_get_balance(another_signer.address)
    assert acc1_balance_after == to_transfer
    assert root_balance - root_balance_after > to_transfer

    # Not enough gas
    with pytest.raises(
        ProviderError, match=re.escape("Invalid transaction: Message.gas cannot be negative")
    ):
        await session.transfer(root_signer, another_signer.address, to_transfer, gas=20000)


async def test_transfer_failed(local_provider, session, root_signer, another_signer):
    # TODO: it would be nice to reproduce the actual situation where this could happen
    # (tranfer was accepted for mining, but failed in the process,
    # and the resulting receipt has a 0 status).
    orig_rpc = local_provider.rpc

    def mock_rpc(method, *args):
        result = orig_rpc(method, *args)
        if method == "eth_getTransactionReceipt":
            result["status"] = "0x0"
        return result

    with monkeypatched(local_provider, "rpc", mock_rpc):
        with pytest.raises(TransactionFailed, match="Transfer failed"):
            await session.transfer(root_signer, another_signer.address, Amount.ether(10))


async def test_deploy(local_provider, session, compiled_contracts, root_signer):
    basic_contract = compiled_contracts["BasicContract"]
    construction_error = compiled_contracts["TestErrors"]
    payable_constructor = compiled_contracts["PayableConstructor"]

    # Normal deploy
    deployed_contract = await session.deploy(root_signer, basic_contract.constructor(123))
    result = await session.eth_call(deployed_contract.method.getState(456))
    assert result == (123 + 456,)

    with pytest.raises(ValueError, match="This constructor does not accept an associated payment"):
        await session.deploy(root_signer, basic_contract.constructor(1), Amount.ether(1))

    # Explicit payment equal to zero is the same as no payment
    await session.deploy(root_signer, basic_contract.constructor(1), Amount.ether(0))

    # Payable constructor
    contract = await session.deploy(
        root_signer, payable_constructor.constructor(1), Amount.ether(1)
    )
    balance = await session.eth_get_balance(contract.address)
    assert balance == Amount.ether(1)

    # When gas is set manually, the gas estimation step is skipped,
    # and we don't see the actual error, only the failed transaction.
    with pytest.raises(TransactionFailed, match="Deploy failed"):
        await session.deploy(root_signer, construction_error.constructor(0), gas=300000)

    # Test the provider returning an empty `contractAddress`
    orig_rpc = local_provider.rpc

    def mock_rpc(method, *args):
        result = orig_rpc(method, *args)
        if method == "eth_getTransactionReceipt":
            result["contractAddress"] = None
        return result

    with monkeypatched(local_provider, "rpc", mock_rpc):
        with pytest.raises(
            BadResponseFormat,
            match=(
                "The deploy transaction succeeded, "
                "but `contractAddress` is not present in the receipt"
            ),
        ):
            await session.deploy(root_signer, basic_contract.constructor(0))


async def test_transact(session, compiled_contracts, root_signer):
    basic_contract = compiled_contracts["BasicContract"]

    # Normal transact
    deployed_contract = await session.deploy(root_signer, basic_contract.constructor(123))
    await session.transact(root_signer, deployed_contract.method.setState(456))
    result = await session.eth_call(deployed_contract.method.getState(789))
    assert result == (456 + 789,)

    with pytest.raises(
        ValueError, match="This method is non-mutating, use `eth_call` to invoke it"
    ):
        await session.transact(root_signer, deployed_contract.method.getState(456))

    with pytest.raises(ValueError, match="This method does not accept an associated payment"):
        await session.transact(root_signer, deployed_contract.method.setState(456), Amount.ether(1))

    # Explicit payment equal to zero is the same as no payment
    await session.transact(root_signer, deployed_contract.method.setState(456), Amount.ether(0))

    # Payable transact
    await session.transact(
        root_signer, deployed_contract.method.payableSetState(456), Amount.ether(1)
    )
    balance = await session.eth_get_balance(deployed_contract.address)
    assert balance == Amount.ether(1)

    # Not enough gas
    with pytest.raises(TransactionFailed, match="Transact failed"):
        await session.transact(root_signer, deployed_contract.method.faultySetState(0), gas=300000)


async def test_transact_with_pending_state(
    local_provider, session, compiled_contracts, root_signer
):
    # Test that a newly submitted transaction uses the pending state and not the finalized state

    basic_contract = compiled_contracts["BasicContract"]
    deployed_contract = await session.deploy(root_signer, basic_contract.constructor(123))

    local_provider.disable_auto_mine_transactions()
    await session.broadcast_transact(root_signer, deployed_contract.method.setState(456))

    with pytest.raises(ContractLegacyError, match="Check succeeded"):
        await session.broadcast_transact(
            root_signer, deployed_contract.method.doubleStateAndCheck(456 * 2)
        )


async def test_transact_and_return_events(
    autojump_clock,  # noqa: ARG001
    local_provider,
    session,
    compiled_contracts,
    root_signer,
    another_signer,
):
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))

    basic_contract = compiled_contracts["BasicContract"]

    deployed_contract = await session.deploy(root_signer, basic_contract.constructor(123))

    event1 = deployed_contract.event.Event1
    event2 = deployed_contract.event.Event2

    def results_for(x):
        return {
            event1: [{"value": x}, {"value": x + 1}],
            event2: [{"value": x + 2}, {"value": x + 3}],
        }

    # Normal operation: one relevant transaction in the block

    x = 1
    result = await session.transact(
        root_signer,
        deployed_contract.method.emitMultipleEvents(x),
        return_events=[event1, event2],
    )
    assert result == results_for(x)

    # Two transactions for the same method in the same block -
    # we need to be able to only pick up the results from the relevant transaction receipt

    local_provider.disable_auto_mine_transactions()

    results = {}

    async def transact(signer, x):
        result = await session.transact(
            signer, deployed_contract.method.emitMultipleEvents(x), return_events=[event1, event2]
        )
        results[x] = result

    async def delayed_enable_mining():
        await trio.sleep(5)
        local_provider.enable_auto_mine_transactions()

    x1 = 1
    x2 = 2
    async with trio.open_nursery() as nursery:
        nursery.start_soon(transact, root_signer, x1)
        nursery.start_soon(transact, another_signer, x2)
        nursery.start_soon(delayed_enable_mining)

    assert results[x1] == results_for(x1)
    assert results[x2] == results_for(x2)


async def test_get_block(session, root_signer, another_signer):
    to_transfer = Amount.ether(10)
    await session.transfer(root_signer, another_signer.address, to_transfer)

    block_info = await session.eth_get_block_by_number(1, with_transactions=True)
    assert all(isinstance(tx, TxInfo) for tx in block_info.transactions)

    block_info2 = await session.eth_get_block_by_hash(block_info.hash_, with_transactions=True)
    assert block_info2 == block_info

    # no transactions
    block_info = await session.eth_get_block_by_number(1)
    assert all(isinstance(tx, TxHash) for tx in block_info.transactions)

    # non-existent block
    block_info = await session.eth_get_block_by_number(100, with_transactions=True)
    assert block_info is None
    block_info = await session.eth_get_block_by_hash(
        BlockHash(b"\x00" * 32), with_transactions=True
    )
    assert block_info is None


async def test_get_block_pending(local_provider, session, root_signer, another_signer):
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))

    local_provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(
        root_signer, another_signer.address, Amount.ether(10)
    )

    block_info = await session.eth_get_block_by_number(BlockLabel.PENDING, with_transactions=True)
    assert block_info.number == 2
    assert block_info.hash_ is None
    assert block_info.nonce is None
    assert block_info.miner is None
    assert block_info.total_difficulty is None
    assert len(block_info.transactions) == 1
    assert block_info.transactions[0].hash_ == tx_hash
    assert block_info.transactions[0].value == Amount.ether(10)

    block_info = await session.eth_get_block_by_number(BlockLabel.PENDING, with_transactions=False)
    assert len(block_info.transactions) == 1
    assert block_info.transactions[0] == tx_hash


async def test_eth_get_transaction_by_hash(local_provider, session, root_signer, another_signer):
    to_transfer = Amount.ether(1)

    tx_hash = await session.broadcast_transfer(root_signer, another_signer.address, to_transfer)
    tx_info = await session.eth_get_transaction_by_hash(tx_hash)
    assert tx_info.value == to_transfer

    non_existent = TxHash(b"abcd" * 8)
    tx_info = await session.eth_get_transaction_by_hash(non_existent)
    assert tx_info is None

    local_provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(root_signer, another_signer.address, to_transfer)
    tx_info = await session.eth_get_transaction_by_hash(tx_hash)

    assert tx_info.block_number == 2
    assert tx_info.block_hash is None
    assert tx_info.transaction_index is None
    assert tx_info.value == to_transfer


async def test_eth_get_code(session, root_signer, compiled_contracts):
    compiled_contract = compiled_contracts["EmptyContract"]
    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor(123))
    bytecode = await session.eth_get_code(deployed_contract.address, block=BlockLabel.LATEST)

    # The bytecode being deployed is not the code that will be stored on chain,
    # but some code that, having been executed, returns the code that will be stored on chain.
    # So all we can do is check that the code stored on chain is a part of the initialization code.
    assert bytecode in compiled_contract.bytecode


async def test_eth_get_storage_at(session, root_signer, compiled_contracts):
    x = 0xAB
    y_key = Address(os.urandom(20))
    y_val = 0xCD

    compiled_contract = compiled_contracts["Storage"]
    deployed_contract = await session.deploy(
        root_signer, compiled_contract.constructor(x, y_key, y_val)
    )

    # Get the regular stored value
    storage = await session.eth_get_storage_at(
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
    storage = await session.eth_get_storage_at(
        deployed_contract.address, position, block=BlockLabel.LATEST
    )
    assert storage == b"\x00" * 31 + y_val.to_bytes(1, byteorder="big")


async def test_eth_get_filter_changes_bad_response(local_provider, session, monkeypatch):
    block_filter = await session.eth_new_block_filter()

    def mock_rpc(_method, *_args):
        return {"foo": 1}

    monkeypatch.setattr(local_provider, "rpc", mock_rpc)

    with pytest.raises(
        BadResponseFormat,
        match=r"eth_getFilterChanges: Can only structure a tuple or a list into a tuple generic",
    ):
        await session.eth_get_filter_changes(block_filter)


async def test_block_filter(session, root_signer, another_signer):
    to_transfer = Amount.ether(1)

    await session.transfer(root_signer, another_signer.address, to_transfer)

    block_filter = await session.eth_new_block_filter()

    await session.transfer(root_signer, another_signer.address, to_transfer)
    await session.transfer(root_signer, another_signer.address, to_transfer)

    last_block = await session.eth_get_block_by_number(BlockLabel.LATEST)
    prev_block = await session.eth_get_block_by_number(last_block.number - 1)

    block_hashes = await session.eth_get_filter_changes(block_filter)
    assert block_hashes == (prev_block.hash_, last_block.hash_)

    await session.transfer(root_signer, another_signer.address, to_transfer)

    block_hashes = await session.eth_get_filter_changes(block_filter)
    last_block = await session.eth_get_block_by_number(BlockLabel.LATEST)
    assert block_hashes == (last_block.hash_,)

    block_hashes = await session.eth_get_filter_changes(block_filter)
    assert len(block_hashes) == 0


async def test_pending_transaction_filter(local_provider, session, root_signer, another_signer):
    transaction_filter = await session.eth_new_pending_transaction_filter()

    to_transfer = Amount.ether(1)

    local_provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(root_signer, another_signer.address, to_transfer)
    tx_hashes = await session.eth_get_filter_changes(transaction_filter)
    assert tx_hashes == (tx_hash,)


async def test_eth_get_logs(
    monkeypatch, local_provider, session, compiled_contracts, root_signer, another_signer
):
    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))
    await session.transact(root_signer, contract1.method.deposit(b"1234"))
    await session.transact(another_signer, contract2.method.deposit2(b"4567"))

    entries = await session.eth_get_logs(source=contract2.address)
    assert len(entries) == 1
    assert entries[0].address == contract2.address
    assert (
        normalize_topics(entries[0].topics)
        == contract2.abi.event.Deposit2(another_signer.address, b"4567").topics
    )

    entries = await session.eth_get_logs(
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

    def mock_rpc(_method, *_args):
        return {"foo": 1}

    monkeypatch.setattr(local_provider, "rpc", mock_rpc)

    with pytest.raises(
        BadResponseFormat,
        match=r"eth_getLogs: Can only structure a tuple or a list into a tuple generic",
    ):
        await session.eth_get_logs(source=contract2.address)


async def test_eth_get_filter_logs(session, compiled_contracts, root_signer, another_signer):
    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))

    log_filter = await session.eth_new_filter()
    await session.transact(root_signer, contract1.method.deposit(b"1234"))
    await session.transact(another_signer, contract2.method.deposit2(b"4567"))

    entries = await session.eth_get_filter_logs(log_filter)
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


async def test_log_filter_all(session, compiled_contracts, root_signer, another_signer):
    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))

    log_filter = await session.eth_new_filter()
    await session.transact(root_signer, contract1.method.deposit(b"1234"))
    await session.transact(another_signer, contract2.method.deposit2(b"4567"))

    entries = await session.eth_get_filter_changes(log_filter)
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


async def test_log_filter_by_address(session, compiled_contracts, root_signer, another_signer):
    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))

    # Filter by a single address

    log_filter = await session.eth_new_filter(source=contract2.address)
    await session.transact(root_signer, contract1.method.deposit(b"1234"))
    await session.transact(root_signer, contract2.method.deposit2(b"4567"))

    entries = await session.eth_get_filter_changes(log_filter)
    assert len(entries) == 1
    assert entries[0].address == contract2.address
    assert (
        normalize_topics(entries[0].topics)
        == contract2.abi.event.Deposit2(root_signer.address, b"4567").topics
    )

    # Filter by several addresses

    contract3 = await session.deploy(another_signer, basic_contract.constructor(123))

    log_filter = await session.eth_new_filter(source=[contract1.address, contract3.address])
    await session.transact(root_signer, contract1.method.deposit(b"1111"))
    await session.transact(root_signer, contract2.method.deposit(b"2222"))
    await session.transact(root_signer, contract3.method.deposit(b"3333"))

    entries = await session.eth_get_filter_changes(log_filter)
    assert len(entries) == 2
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


async def test_log_filter_by_topic(session, compiled_contracts, root_signer, another_signer):
    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))

    # Filter by a specific topic or None at each position

    log_filter = await session.eth_new_filter(event_filter=contract2.abi.event.Deposit2(id=b"4567"))
    # filtered out, wrong event type
    await session.transact(root_signer, contract1.method.deposit(b"4567"))
    # matches the filter
    await session.transact(root_signer, contract1.method.deposit2(b"4567"))
    # filtered out, wrong value
    await session.transact(another_signer, contract2.method.deposit2(b"7890"))
    # matches the filter
    await session.transact(another_signer, contract2.method.deposit2(b"4567"))

    entries = await session.eth_get_filter_changes(log_filter)
    assert len(entries) == 2
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
    log_filter = await session.eth_new_filter(event_filter=event_filter)
    await session.transact(root_signer, contract1.method.deposit(b"1111"))
    await session.transact(root_signer, contract1.method.deposit2(b"1111"))  # filtered out
    await session.transact(root_signer, contract1.method.deposit(b"2222"))  # filtered out
    await session.transact(another_signer, contract2.method.deposit(b"3333"))

    entries = await session.eth_get_filter_changes(log_filter)
    assert len(entries) == 2
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


async def test_log_filter_by_block_num(session, compiled_contracts, root_signer, another_signer):
    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))

    await session.transact(root_signer, contract1.method.deposit(b"1111"))
    block_num = await session.eth_block_number()
    log_filter = await session.eth_new_filter(from_block=block_num + 1, to_block=block_num + 3)

    await session.transact(root_signer, contract1.method.deposit(b"2222"))  # filter will start here
    await session.transact(root_signer, contract1.method.deposit(b"3333"))
    await session.transact(root_signer, contract1.method.deposit(b"4444"))  # filter will stop here
    await session.transact(root_signer, contract1.method.deposit(b"5555"))

    entries = await session.eth_get_filter_changes(log_filter)

    # The range in the filter is inclusive
    assert [entry.block_number for entry in entries] == list(range(block_num + 1, block_num + 4))
    assert [normalize_topics(entry.topics) for entry in entries] == [
        contract1.abi.event.Deposit(root_signer.address, b"2222").topics,
        contract1.abi.event.Deposit(root_signer.address, b"3333").topics,
        contract1.abi.event.Deposit(root_signer.address, b"4444").topics,
    ]


async def test_block_filter_high_level(
    autojump_clock,  # noqa: ARG001
    session,
    root_signer,
    another_signer,
):
    block_hashes = []

    async def observer():
        # This loop always exits via break
        async for block_hash in session.iter_blocks(poll_interval=1):  # pragma: no branch
            block_hashes.append(block_hash)
            if len(block_hashes) == 3:
                break

    await session.transfer(root_signer, another_signer.address, Amount.ether(1))

    async with trio.open_nursery() as nursery:
        nursery.start_soon(observer)
        await trio.sleep(2)
        await session.transfer(root_signer, another_signer.address, Amount.ether(2))
        await session.transfer(root_signer, another_signer.address, Amount.ether(3))
        await trio.sleep(3)
        await session.transfer(root_signer, another_signer.address, Amount.ether(4))
        await trio.sleep(1)
        await session.transfer(root_signer, another_signer.address, Amount.ether(5))

    for i, block_hash in enumerate(block_hashes):
        block_info = await session.eth_get_block_by_hash(block_hash, with_transactions=True)
        assert block_info.transactions[0].value == Amount.ether(i + 2)


async def test_pending_transaction_filter_high_level(
    autojump_clock,  # noqa: ARG001
    session,
    root_signer,
    another_signer,
):
    tx_hashes = []

    async def observer():
        # This loop always exits via break
        async for tx_hash in session.iter_pending_transactions(  # pragma: no branch
            poll_interval=1
        ):
            tx_hashes.append(tx_hash)
            if len(tx_hashes) == 3:
                break

    await session.transfer(root_signer, another_signer.address, Amount.ether(1))

    async with trio.open_nursery() as nursery:
        nursery.start_soon(observer)
        await trio.sleep(2)
        await session.transfer(root_signer, another_signer.address, Amount.ether(2))
        await session.transfer(root_signer, another_signer.address, Amount.ether(3))
        await trio.sleep(3)
        await session.transfer(root_signer, another_signer.address, Amount.ether(4))
        await trio.sleep(1)
        await session.transfer(root_signer, another_signer.address, Amount.ether(5))

    for i, tx_hash in enumerate(tx_hashes):
        tx_info = await session.eth_get_transaction_by_hash(tx_hash)
        assert tx_info.value == Amount.ether(i + 2)


async def test_event_filter_high_level(
    autojump_clock,  # noqa: ARG001
    session,
    compiled_contracts,
    root_signer,
    another_signer,
):
    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))

    events = []

    async def observer():
        event_filter = contract2.event.Deposit2(id=b"1111")
        # This loop always exits via break
        async for event in session.iter_events(event_filter, poll_interval=1):  # pragma: no branch
            events.append(event)
            if len(events) == 3:
                break

    async with trio.open_nursery() as nursery:
        nursery.start_soon(observer)
        await trio.sleep(2)

        # filtered out, wrong event type
        await session.transact(root_signer, contract1.method.deposit(b"1111"))
        # filtered out, wrong contract address
        await session.transact(root_signer, contract1.method.deposit2(b"1111"))
        # filtered out, wrong value
        await session.transact(another_signer, contract2.method.deposit2(b"7890"))
        # matches the filter
        await session.transact(
            root_signer, contract2.method.deposit2(b"1111"), amount=Amount.wei(1)
        )
        await session.transact(
            another_signer, contract2.method.deposit2(b"1111"), amount=Amount.wei(2)
        )
        await session.transact(
            another_signer, contract2.method.deposit2(b"1111"), amount=Amount.wei(3)
        )

    assert events[0] == {"from_": root_signer.address, "id": b"1111", "value": 1, "value2": 2}
    assert events[1] == {"from_": another_signer.address, "id": b"1111", "value": 2, "value2": 3}
    assert events[2] == {"from_": another_signer.address, "id": b"1111", "value": 3, "value2": 4}


async def test_unknown_rpc_status_code(local_provider, session, monkeypatch):
    def mock_rpc(_method, *_args):
        # This is a known exception type, and it will be transferred through the network
        # keeping the status code.
        raise RPCError(666, "this method is possessed")

    monkeypatch.setattr(local_provider, "rpc", mock_rpc)

    with pytest.raises(ProviderError, match=r"Provider error \(666\): this method is possessed"):
        await session.net_version()


async def check_rpc_error(awaitable, expected_code, expected_message, expected_data):
    with pytest.raises(ProviderError) as exc:
        await awaitable

    assert exc.value.code == expected_code
    assert exc.value.message == expected_message
    assert exc.value.data == expected_data


async def test_contract_exceptions(session, root_signer, compiled_contracts):
    compiled_contract = compiled_contracts["TestErrors"]
    contract = await session.deploy(root_signer, compiled_contract.constructor(999))

    error_selector = keccak(b"Error(string)")[:4]
    custom_error_selector = keccak(b"CustomError(uint256)")[:4]

    # `require(condition)`
    kwargs = dict(
        expected_code=RPCErrorCode.SERVER_ERROR,
        expected_message="execution reverted",
        expected_data=None,
    )
    await check_rpc_error(session.eth_call(contract.method.viewError(0)), **kwargs)

    # `require(condition, message)`
    kwargs = dict(
        expected_code=RPCErrorCode.EXECUTION_ERROR,
        expected_message="execution reverted",
        expected_data=error_selector + encode_args((abi.string, "require(string)")),
    )
    await check_rpc_error(session.eth_call(contract.method.viewError(1)), **kwargs)

    # `revert()`
    kwargs = dict(
        expected_code=RPCErrorCode.SERVER_ERROR,
        expected_message="execution reverted",
        expected_data=None,
    )
    await check_rpc_error(session.eth_call(contract.method.viewError(2)), **kwargs)

    # `revert(message)`
    kwargs = dict(
        expected_code=RPCErrorCode.EXECUTION_ERROR,
        expected_message="execution reverted",
        expected_data=error_selector + encode_args((abi.string, "revert(string)")),
    )
    await check_rpc_error(session.eth_call(contract.method.viewError(3)), **kwargs)

    # `revert CustomError(...)`
    kwargs = dict(
        expected_code=RPCErrorCode.EXECUTION_ERROR,
        expected_message="execution reverted",
        expected_data=custom_error_selector + encode_args((abi.uint(256), 4)),
    )
    await check_rpc_error(session.eth_call(contract.method.viewError(4)), **kwargs)


async def test_contract_panics(session, root_signer, compiled_contracts):
    compiled_contract = compiled_contracts["TestErrors"]
    contract = await session.deploy(root_signer, compiled_contract.constructor(999))

    panic_selector = keccak(b"Panic(uint256)")[:4]

    await check_rpc_error(
        session.eth_call(contract.method.viewPanic(0)),
        expected_code=RPCErrorCode.EXECUTION_ERROR,
        expected_message="execution reverted",
        expected_data=panic_selector + encode_args((abi.uint(256), 0x01)),
    )

    await check_rpc_error(
        session.eth_call(contract.method.viewPanic(1)),
        expected_code=RPCErrorCode.EXECUTION_ERROR,
        expected_message="execution reverted",
        expected_data=panic_selector + encode_args((abi.uint(256), 0x11)),
    )


async def test_contract_exceptions_high_level(session, root_signer, compiled_contracts):
    compiled_contract = compiled_contracts["TestErrors"]
    contract = await session.deploy(root_signer, compiled_contract.constructor(999))

    with pytest.raises(ContractPanic) as exc:
        await session.estimate_transact(root_signer.address, contract.method.transactPanic(1))
    assert exc.value.reason == ContractPanic.Reason.OVERFLOW

    with pytest.raises(ContractLegacyError) as exc:
        await session.estimate_transact(root_signer.address, contract.method.transactError(0))
    assert exc.value.message == ""

    with pytest.raises(ContractLegacyError) as exc:
        await session.estimate_transact(root_signer.address, contract.method.transactError(1))
    assert exc.value.message == "require(string)"

    with pytest.raises(ContractError) as exc:
        await session.estimate_transact(root_signer.address, contract.method.transactError(4))
    assert exc.value.error == contract.error.CustomError
    assert exc.value.data == {"x": 4}

    # Check that the same works for deployment

    with pytest.raises(ContractError) as exc:
        await session.estimate_deploy(root_signer.address, compiled_contract.constructor(4))
    assert exc.value.error == contract.error.CustomError
    assert exc.value.data == {"x": 4}


async def test_unknown_error_reasons(local_provider, session, compiled_contracts, root_signer):
    compiled_contract = compiled_contracts["TestErrors"]
    contract = await session.deploy(root_signer, compiled_contract.constructor(999))

    orig_rpc = local_provider.rpc

    # Provider returns an unknown panic code

    def mock_rpc(method, *args):
        if method == "eth_estimateGas":
            # Invalid selector
            data = PANIC_ERROR.selector + encode_args((abi.uint(256), 888))
            raise RPCError(RPCErrorCode.EXECUTION_ERROR, "execution reverted", data)
        return orig_rpc(method, *args)

    with monkeypatched(local_provider, "rpc", mock_rpc):
        with pytest.raises(ContractPanic, match=r"ContractPanicReason.UNKNOWN"):
            await session.estimate_transact(root_signer.address, contract.method.transactPanic(999))

    # Provider returns an unknown error (a selector not present in the ABI)

    def mock_rpc(method, *args):
        if method == "eth_estimateGas":
            # Invalid selector
            data = b"1234" + encode_args((abi.uint(256), 1))
            raise RPCError(RPCErrorCode.EXECUTION_ERROR, "execution reverted", data)
        return orig_rpc(method, *args)

    with monkeypatched(local_provider, "rpc", mock_rpc):
        with pytest.raises(
            ProviderError,
            match=r"Provider error \(RPCErrorCode\.EXECUTION_ERROR\): execution reverted",
        ):
            await session.estimate_transact(root_signer.address, contract.method.transactPanic(999))

    # Provider returns an error with an unknown RPC code

    def mock_rpc(method, *args):
        if method == "eth_estimateGas":
            # Invalid selector
            data = PANIC_ERROR.selector + encode_args((abi.uint(256), 0))
            raise RPCError(12345, "execution reverted", data)
        return orig_rpc(method, *args)

    with monkeypatched(local_provider, "rpc", mock_rpc):
        with pytest.raises(ProviderError, match=r"Provider error \(12345\): execution reverted"):
            await session.estimate_transact(root_signer.address, contract.method.transactPanic(999))
