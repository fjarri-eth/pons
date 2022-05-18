from contextlib import contextmanager
import os
from pathlib import Path

from eth_account import Account
import pytest
import trio

from pons import (
    abi,
    ABIDecodingError,
    AccountSigner,
    Address,
    Amount,
    Client,
    ContractABI,
    DeployedContract,
    ReadMethod,
    TxHash,
    BlockHash,
    Block,
    LogTopic,
)
from pons._client import BadResponseFormat, ExecutionFailed, ProviderError, TransactionFailed

from .compile import compile_file
from .provider_server import ServerHandle
from .provider import EthereumTesterProvider


@pytest.fixture(params=["direct", "http"])
async def provider(request, test_provider, nursery):
    if request.param == "direct":
        yield test_provider
    else:
        handle = ServerHandle(test_provider)
        await nursery.start(handle)
        yield handle.http_provider
        handle.shutdown()


@pytest.fixture
async def session(provider):
    client = Client(provider=provider)
    async with client.session() as session:
        yield session


@pytest.fixture
def compiled_contracts():
    path = Path(__file__).resolve().parent / "TestClient.sol"
    yield compile_file(path)


@contextmanager
def monkeypatched(obj, attr, patch):
    original_value = getattr(obj, attr)
    setattr(obj, attr, patch)
    yield obj
    setattr(obj, attr, original_value)


async def test_net_version(test_provider, session):
    net_version1 = await session.net_version()
    assert net_version1 == "0"

    # This is not going to get called
    def wrong_net_version():
        raise NotImplementedError()  # pragma: no cover

    # The result should have been cached the first time
    with monkeypatched(test_provider, "net_version", wrong_net_version):
        net_version2 = await session.net_version()
    assert net_version1 == net_version2


async def test_net_version_type_check(test_provider, session):
    # Provider returning a bad value
    with monkeypatched(test_provider, "net_version", lambda: 0):
        with pytest.raises(BadResponseFormat, match="net_version: expected a string result"):
            net_version = await session.net_version()


async def test_eth_chain_id(test_provider, session):
    chain_id1 = await session.eth_chain_id()
    assert chain_id1 == 2299111 * 57099167

    # This is not going to get called
    def wrong_chain_id():
        raise NotImplementedError()  # pragma: no cover

    # The result should have been cached the first time
    with monkeypatched(test_provider, "eth_chain_id", wrong_chain_id):
        chain_id2 = await session.eth_chain_id()
    assert chain_id1 == chain_id2


async def test_eth_get_balance(test_provider, session, root_signer, another_signer):
    to_transfer = Amount.ether(10)
    await session.transfer(root_signer, another_signer.address, to_transfer)
    acc1_balance = await session.eth_get_balance(another_signer.address)
    assert acc1_balance == to_transfer

    # Non-existent address (which is technically just an unfunded address)
    random_addr = Address(os.urandom(20))
    balance = await session.eth_get_balance(random_addr)
    assert balance == Amount.ether(0)


async def test_eth_get_transaction_receipt(test_provider, session, root_signer, another_signer):

    test_provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(
        root_signer, another_signer.address, Amount.ether(10)
    )
    receipt = await session.eth_get_transaction_receipt(tx_hash)
    assert receipt is None

    test_provider.enable_auto_mine_transactions()
    receipt = await session.eth_get_transaction_receipt(tx_hash)
    assert receipt.succeeded

    # A non-existent transaction
    receipt = await session.eth_get_transaction_receipt(TxHash(os.urandom(32)))
    assert receipt is None


async def test_eth_get_transaction_count(test_provider, session, root_signer, another_signer):
    assert await session.eth_get_transaction_count(root_signer.address) == 0
    await session.transfer(root_signer, another_signer.address, Amount.ether(10))
    assert await session.eth_get_transaction_count(root_signer.address) == 1


async def test_wait_for_transaction_receipt(
    test_provider, session, root_signer, another_signer, autojump_clock
):

    to_transfer = Amount.ether(10)
    test_provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(root_signer, another_signer.address, to_transfer)

    # The receipt won't be available until we mine, so the waiting should time out
    start_time = trio.current_time()
    try:
        with trio.fail_after(5):
            receipt = await session.wait_for_transaction_receipt(tx_hash)
    except trio.TooSlowError:
        pass
    end_time = trio.current_time()
    assert end_time - start_time == 5

    # Now let's enable mining while we wait for the receipt
    receipt = None

    async def get_receipt():
        nonlocal receipt
        receipt = await session.wait_for_transaction_receipt(tx_hash)

    async def delayed_enable_mining():
        await trio.sleep(5)
        test_provider.enable_auto_mine_transactions()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(get_receipt)
        nursery.start_soon(delayed_enable_mining)

    assert receipt.succeeded


async def test_eth_call(test_provider, session, compiled_contracts, root_signer):
    compiled_contract = compiled_contracts["BasicContract"]
    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor(123))
    result = await session.eth_call(deployed_contract.read.getState(456))
    assert result == [123 + 456]


async def test_eth_call_decoding_error(test_provider, session, compiled_contracts, root_signer):
    """
    Tests that `eth_call()` propagates an error on mismatch of the declared output signature
    and the bytestring received from the provider (as opposed to wrapping it in another exception).
    """
    compiled_contract = compiled_contracts["BasicContract"]
    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor(123))

    wrong_abi = ContractABI(
        read=[
            ReadMethod(
                name="getState",
                inputs=[abi.uint(256)],
                # the actual method in in BasicContract returns only one uint256
                outputs=[abi.uint(256), abi.uint(256)],
            )
        ]
    )
    wrong_contract = DeployedContract(abi=wrong_abi, address=deployed_contract.address)

    expected_message = (
        r"Could not decode the return value with the expected signature \(uint256,uint256\): "
        r"Tried to read 32 bytes.  Only got 0 bytes"
    )

    with pytest.raises(ABIDecodingError, match=expected_message):
        await session.eth_call(wrong_contract.read.getState(456))


async def test_estimate_deploy(test_provider, session, compiled_contracts, root_signer):
    compiled_contract = compiled_contracts["ConstructionError"]
    gas = await session.estimate_deploy(compiled_contract.constructor(1))
    assert isinstance(gas, int) and gas > 0

    with pytest.raises(ExecutionFailed, match="Execution failed: execution reverted"):
        await session.estimate_deploy(compiled_contract.constructor(0))


async def test_estimate_transfer(test_provider, session, root_signer, another_signer):
    gas = await session.estimate_transfer(
        root_signer.address, another_signer.address, Amount.ether(10)
    )
    assert isinstance(gas, int) and gas > 0

    with pytest.raises(
        ProviderError,
        match="Sender does not have enough balance to cover transaction value and gas",
    ):
        await session.estimate_transfer(
            root_signer.address, another_signer.address, Amount.ether(1000)
        )


async def test_estimate_transact(test_provider, session, compiled_contracts, root_signer):
    compiled_contract = compiled_contracts["TransactionError"]
    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor())
    gas = await session.estimate_transact(deployed_contract.write.setState(456))
    assert isinstance(gas, int) and gas > 0

    with pytest.raises(ExecutionFailed, match="Execution failed: execution reverted"):
        await session.estimate_transact(deployed_contract.write.setState(0))


async def test_eth_gas_price(test_provider, session):
    gas_price = await session.eth_gas_price()
    assert isinstance(gas_price, Amount)


async def test_eth_block_number(session, root_signer, another_signer):

    to_transfer = Amount.ether(10)
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    await session.transfer(root_signer, another_signer.address, Amount.ether(2))
    await session.transfer(root_signer, another_signer.address, Amount.ether(3))
    block_num = await session.eth_block_number()

    block_info = await session.eth_get_block_by_number(block_num - 1, with_transactions=True)
    assert block_info.transactions[0].value == Amount.ether(2)


async def test_transfer(test_provider, session, root_signer, another_signer):

    # Regular transfer
    root_balance = await session.eth_get_balance(root_signer.address)
    to_transfer = Amount.ether(10)
    await session.transfer(root_signer, another_signer.address, to_transfer)
    root_balance_after = await session.eth_get_balance(root_signer.address)
    acc1_balance_after = await session.eth_get_balance(another_signer.address)
    assert acc1_balance_after == to_transfer
    assert root_balance - root_balance_after > to_transfer


async def test_transfer_custom_gas(test_provider, session, root_signer, another_signer):

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
    with pytest.raises(ProviderError, match="Insufficient gas"):
        await session.transfer(root_signer, another_signer.address, to_transfer, gas=20000)


async def test_transfer_failed(test_provider, session, root_signer, another_signer):

    # TODO: it would be nice to reproduce the actual situation where this could happen
    # (tranfer was accepted for mining, but failed in the process,
    # and the resulting receipt has a 0 status).
    orig_get_transaction_receipt = test_provider.eth_get_transaction_receipt

    def mock_get_transaction_receipt(tx_hash_hex):
        receipt = orig_get_transaction_receipt(tx_hash_hex)
        receipt["status"] = "0x0"
        return receipt

    with monkeypatched(test_provider, "eth_get_transaction_receipt", mock_get_transaction_receipt):
        with pytest.raises(TransactionFailed, match="Transfer failed"):
            await session.transfer(root_signer, another_signer.address, Amount.ether(10))


async def test_deploy(test_provider, session, compiled_contracts, root_signer):
    basic_contract = compiled_contracts["BasicContract"]
    construction_error = compiled_contracts["ConstructionError"]
    payable_constructor = compiled_contracts["PayableConstructor"]

    # Normal deploy
    deployed_contract = await session.deploy(root_signer, basic_contract.constructor(123))
    result = await session.eth_call(deployed_contract.read.getState(456))
    assert result == [123 + 456]

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

    # Not enough gas
    with pytest.raises(TransactionFailed, match="Deploy failed"):
        await session.deploy(root_signer, construction_error.constructor(0), gas=300000)

    # Test the provider returning an empty `contractAddress`
    orig_get_transaction_receipt = test_provider.eth_get_transaction_receipt

    def mock_get_transaction_receipt(tx_hash_hex):
        receipt = orig_get_transaction_receipt(tx_hash_hex)
        receipt["contractAddress"] = None
        return receipt

    with monkeypatched(test_provider, "eth_get_transaction_receipt", mock_get_transaction_receipt):
        with pytest.raises(
            BadResponseFormat,
            match="The deploy transaction succeeded, but `contractAddress` is not present in the receipt",
        ):
            await session.deploy(root_signer, basic_contract.constructor(0))


async def test_transact(test_provider, session, compiled_contracts, root_signer):
    basic_contract = compiled_contracts["BasicContract"]

    # Normal transact
    deployed_contract = await session.deploy(root_signer, basic_contract.constructor(123))
    await session.transact(root_signer, deployed_contract.write.setState(456))
    result = await session.eth_call(deployed_contract.read.getState(789))
    assert result == [456 + 789]

    with pytest.raises(ValueError, match="This method does not accept an associated payment"):
        await session.transact(root_signer, deployed_contract.write.setState(456), Amount.ether(1))

    # Explicit payment equal to zero is the same as no payment
    await session.transact(root_signer, deployed_contract.write.setState(456), Amount.ether(0))

    # Payable transact
    await session.transact(
        root_signer, deployed_contract.write.payableSetState(456), Amount.ether(1)
    )
    balance = await session.eth_get_balance(deployed_contract.address)
    assert balance == Amount.ether(1)

    # Not enough gas
    with pytest.raises(TransactionFailed, match="Transact failed"):
        await session.transact(root_signer, deployed_contract.write.faultySetState(0), gas=300000)


async def test_get_block(test_provider, session, root_signer, another_signer):
    to_transfer = Amount.ether(10)
    await session.transfer(root_signer, another_signer.address, to_transfer)

    block_info = await session.eth_get_block_by_number(1, with_transactions=True)
    assert block_info.transactions is not None

    block_info2 = await session.eth_get_block_by_hash(block_info.hash, with_transactions=True)
    assert block_info2 == block_info

    # no transactions
    block_info = await session.eth_get_block_by_number(1)
    assert block_info.transactions is None

    # non-existent block
    block_info = await session.eth_get_block_by_number(100, with_transactions=True)
    assert block_info is None
    block_info = await session.eth_get_block_by_hash(
        BlockHash(b"\x00" * 32), with_transactions=True
    )
    assert block_info is None


async def test_eth_get_transaction_by_hash(test_provider, session, root_signer, another_signer):
    to_transfer = Amount.ether(1)

    tx_hash = await session.broadcast_transfer(root_signer, another_signer.address, to_transfer)
    tx_info = await session.eth_get_transaction_by_hash(tx_hash)
    assert tx_info.value == to_transfer

    non_existent = TxHash(b"abcd" * 8)
    tx_info = await session.eth_get_transaction_by_hash(non_existent)
    assert tx_info is None


async def test_block_filter(test_provider, session, root_signer, another_signer):

    to_transfer = Amount.ether(1)

    await session.transfer(root_signer, another_signer.address, to_transfer)

    block_filter = await session.eth_new_block_filter()

    await session.transfer(root_signer, another_signer.address, to_transfer)
    await session.transfer(root_signer, another_signer.address, to_transfer)

    last_block = await session.eth_get_block_by_number(Block.LATEST)
    prev_block = await session.eth_get_block_by_number(last_block.number - 1)

    block_hashes = await session.eth_get_filter_changes(block_filter)
    assert block_hashes == [prev_block.hash, last_block.hash]

    await session.transfer(root_signer, another_signer.address, to_transfer)

    block_hashes = await session.eth_get_filter_changes(block_filter)
    last_block = await session.eth_get_block_by_number(Block.LATEST)
    assert block_hashes == [last_block.hash]

    block_hashes = await session.eth_get_filter_changes(block_filter)
    assert len(block_hashes) == 0


async def test_pending_transaction_filter(test_provider, session, root_signer, another_signer):
    transaction_filter = await session.eth_new_pending_transaction_filter()

    to_transfer = Amount.ether(1)

    test_provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(root_signer, another_signer.address, to_transfer)
    tx_hashes = await session.eth_get_filter_changes(transaction_filter)
    assert tx_hashes == [tx_hash]


async def test_log_filter_all(
    test_provider, session, compiled_contracts, root_signer, another_signer
):

    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))

    log_filter = await session.eth_new_filter()
    await session.transact(root_signer, contract1.write.deposit(b"1234"))
    await session.transact(another_signer, contract2.write.deposit2(b"4567"))

    entries = await session.eth_get_filter_changes(log_filter)
    assert len(entries) == 2
    assert entries[0].address == contract1.address
    assert entries[1].address == contract2.address
    assert entries[0].topics == contract1.abi.event.Deposit.topics(root_signer.address, b"1234")
    assert entries[1].topics == contract2.abi.event.Deposit2.topics(another_signer.address, b"4567")


async def test_log_filter_by_address(
    test_provider, session, compiled_contracts, root_signer, another_signer
):

    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))

    # Filter by a single address

    log_filter = await session.eth_new_filter(source=contract2.address)
    await session.transact(root_signer, contract1.write.deposit(b"1234"))
    await session.transact(root_signer, contract2.write.deposit2(b"4567"))

    entries = await session.eth_get_filter_changes(log_filter)
    assert len(entries) == 1
    assert entries[0].address == contract2.address
    assert entries[0].topics == contract2.abi.event.Deposit2.topics(root_signer.address, b"4567")

    # Filter by several addresses

    contract3 = await session.deploy(another_signer, basic_contract.constructor(123))

    log_filter = await session.eth_new_filter(source=[contract1.address, contract3.address])
    await session.transact(root_signer, contract1.write.deposit(b"1111"))
    await session.transact(root_signer, contract2.write.deposit(b"2222"))
    await session.transact(root_signer, contract3.write.deposit(b"3333"))

    entries = await session.eth_get_filter_changes(log_filter)
    assert len(entries) == 2
    assert entries[0].address == contract1.address
    assert entries[0].topics == contract1.abi.event.Deposit.topics(root_signer.address, b"1111")
    assert entries[1].address == contract3.address
    assert entries[1].topics == contract3.abi.event.Deposit.topics(root_signer.address, b"3333")


async def test_log_filter_by_topic(
    test_provider, session, compiled_contracts, root_signer, another_signer
):

    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))

    # Filter by a specific topic or None at each position

    log_filter = await session.eth_new_filter(
        topics=contract2.abi.event.Deposit2.topics(id=b"4567")
    )
    # filtered out, wrong event type
    await session.transact(root_signer, contract1.write.deposit(b"4567"))
    # matches the filter
    await session.transact(root_signer, contract1.write.deposit2(b"4567"))
    # filtered out, wrong value
    await session.transact(another_signer, contract2.write.deposit2(b"7890"))
    # matches the filter
    await session.transact(another_signer, contract2.write.deposit2(b"4567"))

    entries = await session.eth_get_filter_changes(log_filter)
    assert len(entries) == 2
    assert entries[0].address == contract1.address
    assert entries[0].topics == contract1.abi.event.Deposit2.topics(root_signer.address, b"4567")
    assert entries[1].address == contract2.address
    assert entries[1].topics == contract2.abi.event.Deposit2.topics(another_signer.address, b"4567")

    # Filter by a list of topics

    topics = contract1.abi.event.Deposit.topics(id=[b"1111", b"3333"])
    log_filter = await session.eth_new_filter(topics=topics)
    await session.transact(root_signer, contract1.write.deposit(b"1111"))
    await session.transact(root_signer, contract1.write.deposit2(b"1111"))  # filtered out
    await session.transact(root_signer, contract1.write.deposit(b"2222"))  # filtered out
    await session.transact(another_signer, contract2.write.deposit(b"3333"))

    entries = await session.eth_get_filter_changes(log_filter)
    assert len(entries) == 2
    assert entries[0].address == contract1.address
    assert entries[0].topics == contract1.abi.event.Deposit.topics(root_signer.address, b"1111")
    assert entries[1].address == contract2.address
    assert entries[1].topics == contract2.abi.event.Deposit.topics(another_signer.address, b"3333")


async def test_log_filter_by_block_num(
    test_provider, session, compiled_contracts, root_signer, another_signer
):

    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))

    await session.transact(root_signer, contract1.write.deposit(b"1111"))
    block_num = await session.eth_block_number()
    await session.transact(root_signer, contract1.write.deposit(b"2222"))  # filter will start here
    await session.transact(root_signer, contract1.write.deposit(b"3333"))
    await session.transact(root_signer, contract1.write.deposit(b"4444"))  # filter will stop here
    await session.transact(root_signer, contract1.write.deposit(b"5555"))

    log_filter = await session.eth_new_filter(from_block=block_num + 1, to_block=block_num + 3)
    entries = await session.eth_get_filter_changes(log_filter)

    # The range in the filter is inclusive
    assert [entry.block_number for entry in entries] == list(range(block_num + 1, block_num + 4))
    assert [entry.topics for entry in entries] == [
        contract1.abi.event.Deposit.topics(root_signer.address, b"2222"),
        contract1.abi.event.Deposit.topics(root_signer.address, b"3333"),
        contract1.abi.event.Deposit.topics(root_signer.address, b"4444"),
    ]


async def test_block_filter_high_level(
    autojump_clock, test_provider, session, root_signer, another_signer
):

    block_hashes = []

    async def observer():
        async for block_hash in session.iter_blocks(poll_interval=1):
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
    autojump_clock, test_provider, session, root_signer, another_signer
):

    tx_hashes = []

    async def observer():
        async for tx_hash in session.iter_pending_transactions(poll_interval=1):
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
