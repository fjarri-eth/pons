import re
from pathlib import Path
from typing import Any

import pytest
import trio
from ethereum_rpc import (
    Amount,
    BlockHash,
    ErrorCode,
    RPCError,
    RPCErrorCode,
    TxHash,
    TxInfo,
    TxReceipt,
)
from pytest import MonkeyPatch
from trio.testing import MockClock

from pons import (
    ABIDecodingError,
    AccountSigner,
    BoundEvent,
    Client,
    ClientSession,
    CompiledContract,
    ContractABI,
    ContractError,
    ContractLegacyError,
    ContractPanic,
    DeployedContract,
    LocalProvider,
    Method,
    Mutability,
    abi,
    compile_contract_file,
)
from pons._abi_types import encode_args
from pons._client import BadResponseFormat, ProviderError, TransactionFailed
from pons._contract_abi import PANIC_ERROR
from pons._provider import RPC_JSON


@pytest.fixture
def compiled_contracts() -> dict[str, CompiledContract]:
    path = Path(__file__).resolve().parent / "TestClient.sol"
    return compile_contract_file(path)


async def test_net_version(
    local_provider: LocalProvider, session: ClientSession, monkeypatch: MonkeyPatch
) -> None:
    net_version1 = await session.net_version()
    assert net_version1 == "1"

    # This is not going to get called
    def mock_rpc(*_args: Any) -> RPC_JSON:
        raise NotImplementedError  # pragma: no cover

    # The result should have been cached the first time
    monkeypatch.setattr(local_provider, "rpc", mock_rpc)
    net_version2 = await session.net_version()
    assert net_version1 == net_version2


async def test_net_version_type_check(
    local_provider: LocalProvider, session: ClientSession, monkeypatch: MonkeyPatch
) -> None:
    # Provider returning a bad value
    monkeypatch.setattr(local_provider, "rpc", lambda *_args: 0)
    with pytest.raises(BadResponseFormat, match="net_version: The value must be a string"):
        await session.net_version()


async def test_chain_id(monkeypatch: MonkeyPatch) -> None:
    local_provider = LocalProvider(root_balance=Amount.ether(100), chain_id=123)
    client = Client(local_provider)

    # This is not going to get called
    def mock_rpc(_method: str, *_args: Any) -> RPC_JSON:
        raise NotImplementedError  # pragma: no cover

    async with client.session() as session:
        chain_id1 = await session.chain_id()
        assert chain_id1 == 123

        # The result should have been cached the first time
        monkeypatch.setattr(local_provider, "rpc", mock_rpc)
        chain_id2 = await session.chain_id()
        assert chain_id1 == chain_id2


async def test_get_block(
    session: ClientSession, root_signer: AccountSigner, another_signer: AccountSigner
) -> None:
    to_transfer = Amount.ether(10)
    await session.transfer(root_signer, another_signer.address, to_transfer)

    block_info = await session.get_block(1, with_transactions=True)
    assert block_info is not None
    assert all(isinstance(tx, TxInfo) for tx in block_info.transactions)

    assert block_info.hash_ is not None
    block_info2 = await session.get_block(block_info.hash_, with_transactions=True)
    assert block_info2 is not None
    assert block_info2 == block_info

    # no transactions
    block_info = await session.get_block(1)
    assert block_info is not None
    assert all(isinstance(tx, TxHash) for tx in block_info.transactions)

    # non-existent block
    block_info = await session.get_block(100, with_transactions=True)
    assert block_info is None
    block_info = await session.get_block(BlockHash(b"\x00" * 32), with_transactions=True)
    assert block_info is None


async def test_wait_for_transaction_receipt(
    autojump_clock: MockClock,  # noqa: ARG001
    local_provider: LocalProvider,
    session: ClientSession,
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    to_transfer = Amount.ether(10)
    local_provider.disable_auto_mine_transactions()
    tx_hash = await session.broadcast_transfer(root_signer, another_signer.address, to_transfer)

    # The receipt won't be available until we mine, so the waiting should time out
    timeout = 5
    start_time = trio.current_time()
    with pytest.raises(trio.TooSlowError):
        with trio.fail_after(timeout):
            _receipt = await session.wait_for_transaction_receipt(tx_hash)
    end_time = trio.current_time()
    assert end_time - start_time == timeout

    # Now let's enable mining while we wait for the receipt
    receipt: None | TxReceipt = None

    async def get_receipt() -> None:
        nonlocal receipt
        receipt = await session.wait_for_transaction_receipt(tx_hash)

    async def delayed_enable_mining() -> None:
        await trio.sleep(timeout)
        local_provider.enable_auto_mine_transactions()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(get_receipt)
        nursery.start_soon(delayed_enable_mining)

    assert receipt is not None
    assert receipt.succeeded


async def test_call_contract_error(
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
) -> None:
    """Tests that `call()` correctly decodes a contract error."""
    compiled_contract = compiled_contracts["TestErrors"]
    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor(123))

    with pytest.raises(ContractError) as exc:
        await session.call(deployed_contract.method.viewError(4))
    assert exc.value.error == deployed_contract.error.CustomError
    assert exc.value.data == {"x": 4}


async def test_call_decoding_error(
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
) -> None:
    """
    Tests that `call()` propagates an error on mismatch of the declared output signature
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
        await session.call(wrong_contract.method.getState(456))


async def test_estimate_deploy(
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
) -> None:
    compiled_contract = compiled_contracts["BasicContract"]
    gas = await session.estimate_deploy(root_signer.address, compiled_contract.constructor(1))
    assert isinstance(gas, int)
    assert gas > 0


async def test_estimate_transfer(
    session: ClientSession, root_signer: AccountSigner, another_signer: AccountSigner
) -> None:
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


async def test_estimate_transact(
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
) -> None:
    compiled_contract = compiled_contracts["BasicContract"]
    deployed_contract = await session.deploy(root_signer, compiled_contract.constructor(1))
    gas = await session.estimate_transact(
        root_signer.address, deployed_contract.method.setState(456)
    )
    assert isinstance(gas, int)
    assert gas > 0


async def test_transfer(
    session: ClientSession, root_signer: AccountSigner, another_signer: AccountSigner
) -> None:
    # Regular transfer
    root_balance = await session.get_balance(root_signer.address)
    to_transfer = Amount.ether(10)
    await session.transfer(root_signer, another_signer.address, to_transfer)
    root_balance_after = await session.get_balance(root_signer.address)
    acc1_balance_after = await session.get_balance(another_signer.address)
    assert acc1_balance_after == to_transfer
    assert root_balance - root_balance_after > to_transfer


async def test_transfer_custom_gas(
    session: ClientSession, root_signer: AccountSigner, another_signer: AccountSigner
) -> None:
    root_balance = await session.get_balance(root_signer.address)
    to_transfer = Amount.ether(10)

    # Override gas estimate
    # The standard transfer gas cost is 21000, we're being cautious here.
    await session.transfer(root_signer, another_signer.address, to_transfer, gas=22000)
    root_balance_after = await session.get_balance(root_signer.address)
    acc1_balance_after = await session.get_balance(another_signer.address)
    assert acc1_balance_after == to_transfer
    assert root_balance - root_balance_after > to_transfer

    # Not enough gas
    with pytest.raises(
        ProviderError, match=re.escape("Invalid transaction: Message.gas cannot be negative")
    ):
        await session.transfer(root_signer, another_signer.address, to_transfer, gas=20000)


async def test_transfer_failed(
    local_provider: LocalProvider,
    session: ClientSession,
    root_signer: AccountSigner,
    another_signer: AccountSigner,
    monkeypatch: MonkeyPatch,
) -> None:
    # TODO: it would be nice to reproduce the actual situation where this could happen
    # (tranfer was accepted for mining, but failed in the process,
    # and the resulting receipt has a 0 status).
    orig_rpc = local_provider.rpc

    def mock_rpc(method: str, *args: Any) -> RPC_JSON:
        result = orig_rpc(method, *args)
        if method == "eth_getTransactionReceipt":
            assert isinstance(result, dict)
            result["status"] = "0x0"
        return result

    monkeypatch.setattr(local_provider, "rpc", mock_rpc)
    with pytest.raises(TransactionFailed, match="Transfer failed"):
        await session.transfer(root_signer, another_signer.address, Amount.ether(10))


async def test_deploy(
    local_provider: LocalProvider,
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
    monkeypatch: MonkeyPatch,
) -> None:
    basic_contract = compiled_contracts["BasicContract"]
    construction_error = compiled_contracts["TestErrors"]
    payable_constructor = compiled_contracts["PayableConstructor"]

    # Normal deploy
    deployed_contract = await session.deploy(root_signer, basic_contract.constructor(123))
    result = await session.call(deployed_contract.method.getState(456))
    assert result == (123 + 456,)

    with pytest.raises(ValueError, match="This constructor does not accept an associated payment"):
        await session.deploy(root_signer, basic_contract.constructor(1), Amount.ether(1))

    # Explicit payment equal to zero is the same as no payment
    await session.deploy(root_signer, basic_contract.constructor(1), Amount.ether(0))

    # Payable constructor
    contract = await session.deploy(
        root_signer, payable_constructor.constructor(1), Amount.ether(1)
    )
    balance = await session.get_balance(contract.address)
    assert balance == Amount.ether(1)

    # When gas is set manually, the gas estimation step is skipped,
    # and we don't see the actual error, only the failed transaction.
    with pytest.raises(TransactionFailed, match="Deploy failed"):
        await session.deploy(root_signer, construction_error.constructor(0), gas=300000)

    # Test the provider returning an empty `contractAddress`
    orig_rpc = local_provider.rpc

    def mock_rpc(method: str, *args: Any) -> RPC_JSON:
        result = orig_rpc(method, *args)
        if method == "eth_getTransactionReceipt":
            assert isinstance(result, dict)
            result["contractAddress"] = None
        return result

    monkeypatch.setattr(local_provider, "rpc", mock_rpc)
    with pytest.raises(
        BadResponseFormat,
        match=(
            "The deploy transaction succeeded, but `contractAddress` is not present in the receipt"
        ),
    ):
        await session.deploy(root_signer, basic_contract.constructor(0))


async def test_transact(
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
) -> None:
    basic_contract = compiled_contracts["BasicContract"]

    # Normal transact
    deployed_contract = await session.deploy(root_signer, basic_contract.constructor(123))
    await session.transact(root_signer, deployed_contract.method.setState(456))
    result = await session.call(deployed_contract.method.getState(789))
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
    balance = await session.get_balance(deployed_contract.address)
    assert balance == Amount.ether(1)

    # Not enough gas
    with pytest.raises(TransactionFailed, match="Transact failed"):
        await session.transact(root_signer, deployed_contract.method.faultySetState(0), gas=300000)


async def test_transact_with_pending_state(
    local_provider: LocalProvider,
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
) -> None:
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
    autojump_clock: MockClock,  # noqa: ARG001
    local_provider: LocalProvider,
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))

    basic_contract = compiled_contracts["BasicContract"]

    deployed_contract = await session.deploy(root_signer, basic_contract.constructor(123))

    event1 = deployed_contract.event.Event1
    event2 = deployed_contract.event.Event2

    def results_for(x: int) -> dict[BoundEvent, list[dict[str, Any]]]:
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

    async def transact(signer: AccountSigner, x: int) -> None:
        nonlocal results
        result = await session.transact(
            signer, deployed_contract.method.emitMultipleEvents(x), return_events=[event1, event2]
        )
        results[x] = result

    async def delayed_enable_mining() -> None:
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


async def test_block_filter_high_level(
    autojump_clock: MockClock,  # noqa: ARG001
    session: ClientSession,
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    block_hashes = []

    async def observer() -> None:
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
        block_info = await session.get_block(block_hash, with_transactions=True)
        assert block_info is not None
        assert isinstance(block_info.transactions[0], TxInfo)
        assert block_info.transactions[0].value == Amount.ether(i + 2)


async def test_pending_transaction_filter_high_level(
    autojump_clock: MockClock,  # noqa: ARG001
    session: ClientSession,
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    tx_hashes = []

    async def observer() -> None:
        nonlocal tx_hashes
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
        tx_info = await session.get_transaction(tx_hash)
        assert tx_info is not None
        assert tx_info.value == Amount.ether(i + 2)


async def test_event_filter_high_level(
    autojump_clock: MockClock,  # noqa: ARG001
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    basic_contract = compiled_contracts["BasicContract"]
    await session.transfer(root_signer, another_signer.address, Amount.ether(1))
    contract1 = await session.deploy(root_signer, basic_contract.constructor(123))
    contract2 = await session.deploy(another_signer, basic_contract.constructor(123))

    events = []

    async def observer() -> None:
        nonlocal events
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


async def test_contract_exceptions_high_level(
    session: ClientSession,
    root_signer: AccountSigner,
    compiled_contracts: dict[str, CompiledContract],
) -> None:
    compiled_contract = compiled_contracts["TestErrors"]
    contract = await session.deploy(root_signer, compiled_contract.constructor(999))

    with pytest.raises(ContractPanic) as panic_exc:
        await session.estimate_transact(root_signer.address, contract.method.transactPanic(1))
    assert panic_exc.value.reason == ContractPanic.Reason.OVERFLOW

    with pytest.raises(ContractLegacyError) as legacy_exc:
        await session.estimate_transact(root_signer.address, contract.method.transactError(0))
    assert legacy_exc.value.message == ""

    with pytest.raises(ContractLegacyError) as legacy_exc:
        await session.estimate_transact(root_signer.address, contract.method.transactError(1))
    assert legacy_exc.value.message == "require(string)"

    with pytest.raises(ContractError) as error_exc:
        await session.estimate_transact(root_signer.address, contract.method.transactError(4))
    assert error_exc.value.error == contract.error.CustomError
    assert error_exc.value.data == {"x": 4}

    # Check that the same works for deployment

    with pytest.raises(ContractError) as error_exc:
        await session.estimate_deploy(root_signer.address, compiled_contract.constructor(4))
    assert error_exc.value.error == contract.error.CustomError
    assert error_exc.value.data == {"x": 4}


async def test_unknown_error_reasons(
    local_provider: LocalProvider,
    session: ClientSession,
    compiled_contracts: dict[str, CompiledContract],
    root_signer: AccountSigner,
    monkeypatch: MonkeyPatch,
) -> None:
    compiled_contract = compiled_contracts["TestErrors"]
    contract = await session.deploy(root_signer, compiled_contract.constructor(999))

    orig_rpc = local_provider.rpc

    # Provider returns an unknown panic code

    def mock_rpc_unknown_panic(method: str, *args: Any) -> RPC_JSON:
        if method == "eth_estimateGas":
            # Invalid selector
            data = PANIC_ERROR.selector + encode_args((abi.uint(256), 888))
            raise RPCError.with_code(RPCErrorCode.EXECUTION_ERROR, "execution reverted", data)
        return orig_rpc(method, *args)

    with monkeypatch.context() as mp:
        mp.setattr(local_provider, "rpc", mock_rpc_unknown_panic)
        with pytest.raises(ContractPanic, match=r"ContractPanicReason.UNKNOWN"):
            await session.estimate_transact(root_signer.address, contract.method.transactPanic(999))

    # Provider returns an unknown error (a selector not present in the ABI)

    def mock_rpc_unknown_error(method: str, *args: Any) -> RPC_JSON:
        if method == "eth_estimateGas":
            # Invalid selector
            data = b"1234" + encode_args((abi.uint(256), 1))
            raise RPCError.with_code(RPCErrorCode.EXECUTION_ERROR, "execution reverted", data)
        return orig_rpc(method, *args)

    with monkeypatch.context() as mp:
        mp.setattr(local_provider, "rpc", mock_rpc_unknown_error)
        with pytest.raises(
            ProviderError,
            match=r"Provider error \(RPCErrorCode\.EXECUTION_ERROR\): execution reverted",
        ):
            await session.estimate_transact(root_signer.address, contract.method.transactPanic(999))

    # Provider returns an error with an unknown RPC code

    def mock_rpc_unknown_code(method: str, *args: Any) -> RPC_JSON:
        if method == "eth_estimateGas":
            # Invalid selector
            data = PANIC_ERROR.selector + encode_args((abi.uint(256), 0))
            raise RPCError(ErrorCode(12345), "execution reverted", data)
        return orig_rpc(method, *args)

    with monkeypatch.context() as mp:
        mp.setattr(local_provider, "rpc", mock_rpc_unknown_code)
        with pytest.raises(ProviderError, match=r"Provider error \(12345\): execution reverted"):
            await session.estimate_transact(root_signer.address, contract.method.transactPanic(999))
