from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from enum import Enum
from typing import TYPE_CHECKING, Any, ParamSpec, cast

import anyio
from ethereum_rpc import (
    Address,
    Amount,
    Block,
    BlockHash,
    BlockInfo,
    BlockLabel,
    EstimateGasParams,
    LogEntry,
    RPCError,
    RPCErrorCode,
    TxHash,
    TxInfo,
    TxReceipt,
    Type2Transaction,
    unstructure,
)

from ._client_rpc import BadResponseFormat, ClientSessionRPC
from ._contract import (
    BaseBoundMethodCall,
    BoundConstructorCall,
    BoundEvent,
    BoundEventFilter,
    DeployedContract,
)
from ._contract_abi import (
    LEGACY_ERROR,
    PANIC_ERROR,
    ContractABI,
    Error,
    EventFilter,
    UnknownError,
)
from ._provider import Provider, ProviderError, ProviderSession
from ._signer import Signer

if TYPE_CHECKING:  # pragma: no cover
    from eth_account.types import TransactionDictType


class Client:
    """An Ethereum RPC client."""

    def __init__(self, provider: Provider):
        self._provider = provider
        self._net_version: None | str = None
        self._chain_id: None | int = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator["ClientSession"]:
        """Opens a session to the client allowing the backend to optimize sequential requests."""
        async with self._provider.session() as provider_session:
            client_session = ClientSession(provider_session)
            yield client_session
            # TODO (#58): incorporate cached values from the session back into the client


class TransactionFailed(Exception):
    """
    Raised for invalid transactions that are not contract executions
    (e.g. transfers or contract deployments).
    """


Param = ParamSpec("Param")


class ContractPanicReason(Enum):
    """Reasons leading to a contract call panicking."""

    UNKNOWN = -1
    """Unknown panic code."""

    COMPILER = 0
    """Used for generic compiler inserted panics."""

    ASSERTION = 0x01
    """If you call assert with an argument that evaluates to ``false``."""

    OVERFLOW = 0x11
    """
    If an arithmetic operation results in underflow or overflow
    outside of an ``unchecked { ... }`` block.
    """

    DIVISION_BY_ZERO = 0x12
    """If you divide or modulo by zero (e.g. ``5 / 0`` or ``23 % 0``)."""

    INVALID_ENUM_VALUE = 0x21
    """If you convert a value that is too big or negative into an ``enum`` type."""

    INVALID_ENCODING = 0x22
    """If you access a storage byte array that is incorrectly encoded."""

    EMPTY_ARRAY = 0x31
    """If you call ``.pop()`` on an empty array."""

    OUT_OF_BOUNDS = 0x32
    """
    If you access an array, ``bytesN`` or an array slice at an out-of-bounds or negative index
    (i.e. ``x[i]`` where ``i >= x.length`` or ``i < 0``).
    """

    OUT_OF_MEMORY = 0x41
    """If you allocate too much memory or create an array that is too large."""

    ZERO_DEREFERENCE = 0x51
    """If you call a zero-initialized variable of internal function type."""

    @classmethod
    def from_int(cls, val: int) -> "ContractPanicReason":
        try:
            return cls(val)
        except ValueError:
            return cls.UNKNOWN


class ContractPanic(Exception):
    """A panic raised in a contract call."""

    Reason = ContractPanicReason

    reason: ContractPanicReason
    """Parsed panic reason."""

    @classmethod
    def from_code(cls, code: int) -> "ContractPanic":
        return cls(ContractPanicReason.from_int(code))

    def __init__(self, reason: ContractPanicReason):
        super().__init__(reason)
        self.reason = reason


class ContractLegacyError(Exception):
    """A raised Solidity legacy error (from ``require()`` or ``revert()``)."""

    message: str
    """The error message."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ContractError(Exception):
    """A raised Solidity error (from ``revert SomeError(...)``)."""

    error: Error
    """The recognized ABI Error object."""

    data: dict[str, Any]
    """The unpacked error data, corresponding to the ABI."""

    def __init__(self, error: Error, decoded_data: dict[str, Any]):
        super().__init__(error, decoded_data)
        self.error = error
        self.data = decoded_data


@contextmanager
def convert_errors(abi: ContractABI) -> Iterator[None]:
    try:
        yield
    except ProviderError as exc:
        if isinstance(exc.error, RPCError):
            raise decode_contract_error(abi, exc.error) from exc
        else:
            raise


def decode_contract_error(
    abi: ContractABI, exc: RPCError
) -> ContractPanic | ContractLegacyError | ContractError | ProviderError:
    # A little wonky, but there's no better way to detect legacy errors without a message.
    # Hopefully these are used very rarely.
    if exc.parsed_code == RPCErrorCode.SERVER_ERROR and exc.message == "execution reverted":
        return ContractLegacyError("")
    if exc.parsed_code == RPCErrorCode.EXECUTION_ERROR:
        try:
            error, decoded_data = abi.resolve_error(exc.data or b"")
        except UnknownError:
            return ProviderError(exc)

        if error == PANIC_ERROR:
            return ContractPanic.from_code(decoded_data["code"])
        if error == LEGACY_ERROR:
            return ContractLegacyError(decoded_data["message"])
        return ContractError(error, decoded_data)
    return ProviderError(exc)


class ClientSession:
    """
    An open session to the provider.

    The methods of this class may raise the following exceptions:
    :py:class:`ProviderError`,
    :py:class:`ContractLegacyError`,
    :py:class:`ContractError`,
    :py:class:`ContractPanic`,
    :py:class:`TransactionFailed`,
    :py:class:`BadResponseFormat`,
    :py:class:`ABIDecodingError`,
    """

    def __init__(self, provider_session: ProviderSession):
        self._provider_session = provider_session
        self._net_version: None | str = None
        self._chain_id: None | int = None
        self._rpc = ClientSessionRPC(self._provider_session)

    @property
    def rpc(self) -> ClientSessionRPC:
        return ClientSessionRPC(self._provider_session)

    async def net_version(self) -> str:
        """Calls the ``net_version`` RPC method."""
        if self._net_version is None:
            self._net_version = await self.rpc.net_version()
        return self._net_version

    async def chain_id(self) -> int:
        """Calls the ``eth_chainId`` RPC method."""
        if self._chain_id is None:
            self._chain_id = await self.rpc.eth_chain_id()
        return self._chain_id

    async def wait_for_transaction_receipt(
        self, tx_hash: TxHash, poll_latency: float = 1.0
    ) -> TxReceipt:
        """Queries the transaction receipt waiting for ``poll_latency`` between each attempt."""
        while True:
            receipt = await self._rpc.eth_get_transaction_receipt(tx_hash)
            if receipt is not None:
                return receipt
            await anyio.sleep(poll_latency)

    async def get_balance(self, address: Address, block: Block = BlockLabel.LATEST) -> Amount:
        """Query the balance of ``address`` at ``block``."""
        return await self._rpc.eth_get_balance(address, block=block)

    async def get_transaction(self, tx_hash: TxHash) -> None | TxInfo:
        return await self._rpc.eth_get_transaction_by_hash(tx_hash)

    async def get_block(
        self, block_id: BlockHash | Block, *, with_transactions: bool = False
    ) -> None | BlockInfo:
        if isinstance(block_id, BlockHash):
            return await self._rpc.eth_get_block_by_hash(
                block_id, with_transactions=with_transactions
            )
        return await self._rpc.eth_get_block_by_number(
            block_id, with_transactions=with_transactions
        )

    async def call(
        self,
        call: BaseBoundMethodCall,
        block: Block = BlockLabel.LATEST,
        sender_address: None | Address = None,
    ) -> Any:
        """
        Sends a prepared contact method call to the provided address.
        Returns the decoded output.

        If ``sender_address`` is provided, it will be included in the call
        and affect the return value if the method uses ``msg.sender`` internally.
        """
        with convert_errors(call.contract_abi):
            return await self._rpc.eth_call(call, block=block, sender_address=sender_address)

    async def estimate_deploy(
        self,
        sender_address: Address,
        call: BoundConstructorCall,
        amount: None | Amount = None,
        block: Block = BlockLabel.LATEST,
    ) -> int:
        """
        Estimates the amount of gas required to deploy the contract with the given args.
        Use with the same ``amount`` argument you would use to deploy the contract in production,
        and the ``sender_address`` equal to the address of the transaction signer.

        Raises :py:class:`ContractPanic`, :py:class:`ContractLegacyError`,
        or :py:class:`ContractError` if a known error was caught during the dry run.
        If the error was unknown, falls back to :py:class:`ethereum_rpc.RPCError`.
        """
        params = EstimateGasParams(
            from_=sender_address, data=call.data_bytes, value=amount or Amount(0)
        )
        with convert_errors(call.contract_abi):
            return await self._rpc.eth_estimate_gas(params, block)

    async def estimate_transfer(
        self,
        source_address: Address,
        destination_address: Address,
        amount: Amount,
        block: Block = BlockLabel.LATEST,
    ) -> int:
        """
        Estimates the amount of gas required to transfer ``amount``.
        Raises a :py:class:`ethereum_rpc.RPCError` if there is not enough funds
        in ``source_address``.
        """
        # source_address and amount are optional,
        # but if they are specified, we will fail here instead of later.
        params = EstimateGasParams(from_=source_address, to=destination_address, value=amount)
        return await self._rpc.eth_estimate_gas(params, block)

    async def estimate_transact(
        self,
        sender_address: Address,
        call: BaseBoundMethodCall,
        amount: None | Amount = None,
        block: Block = BlockLabel.LATEST,
    ) -> int:
        """
        Estimates the amount of gas required to transact with a contract.
        Use with the same ``amount`` argument you would use to transact
        with the contract in production,
        and the ``sender_address`` equal to the address of the transaction signer.

        Raises :py:class:`ContractPanic`, :py:class:`ContractLegacyError`,
        or :py:class:`ContractError` if a known error was caught during the dry run.
        If the error was unknown, falls back to :py:class:`ethereum_rpc.RPCError`.
        """
        params = EstimateGasParams(
            from_=sender_address,
            to=call.contract_address,
            data=call.data_bytes,
            value=amount or Amount(0),
        )
        with convert_errors(call.contract_abi):
            return await self._rpc.eth_estimate_gas(params, block)

    async def broadcast_transfer(
        self,
        signer: Signer,
        destination_address: Address,
        amount: Amount,
        gas: None | int = None,
    ) -> TxHash:
        """
        Broadcasts the fund transfer transaction, but does not wait for it to be processed.
        If ``gas`` is ``None``, the required amount of gas is estimated first,
        otherwise the provided value is used.
        """
        chain_id = await self.chain_id()
        if gas is None:
            gas = await self.estimate_transfer(signer.address, destination_address, amount)
        # TODO (#19): implement gas strategies
        max_gas_price = await self._rpc.eth_gas_price()
        max_tip = min(Amount.gwei(1), max_gas_price)
        nonce = await self._rpc.eth_get_transaction_count(signer.address, BlockLabel.PENDING)
        tx = cast(
            "TransactionDictType",
            unstructure(
                Type2Transaction(
                    chain_id=chain_id,
                    to=destination_address,
                    value=amount,
                    gas=gas,
                    max_fee_per_gas=max_gas_price,
                    max_priority_fee_per_gas=max_tip,
                    nonce=nonce,
                )
            ),
        )
        signed_tx = signer.sign_transaction(tx)
        return await self._rpc.eth_send_raw_transaction(signed_tx)

    async def transfer(
        self,
        signer: Signer,
        destination_address: Address,
        amount: Amount,
        gas: None | int = None,
    ) -> None:
        """
        Transfers funds from the address of the attached signer to the destination address.
        If ``gas`` is ``None``, the required amount of gas is estimated first,
        otherwise the provided value is used.
        Waits for the transaction to be confirmed.

        Raises :py:class:`TransactionFailed` if the transaction was submitted successfully,
        but could not be processed.
        """
        tx_hash = await self.broadcast_transfer(signer, destination_address, amount, gas=gas)
        receipt = await self.wait_for_transaction_receipt(tx_hash)
        if not receipt.succeeded:
            raise TransactionFailed(f"Transfer failed (receipt: {receipt})")

    async def deploy(
        self,
        signer: Signer,
        call: BoundConstructorCall,
        amount: None | Amount = None,
        gas: None | int = None,
    ) -> DeployedContract:
        """
        Deploys the contract passing ``args`` to the constructor.
        If ``gas`` is ``None``, the required amount of gas is estimated first,
        otherwise the provided value is used.
        Waits for the transaction to be confirmed.
        ``amount`` denotes the amount of currency to send to the constructor.

        Raises :py:class:`TransactionFailed` if the transaction was submitted successfully,
        but could not be processed.
        If gas estimation is run, see the additional errors that may be raised in the docs for
        :py:meth:`~ClientSession.estimate_deploy`.
        """
        if amount is None:
            amount = Amount(0)

        if not call.payable and amount.as_wei() != 0:
            raise ValueError("This constructor does not accept an associated payment")

        chain_id = await self.chain_id()
        if gas is None:
            gas = await self.estimate_deploy(signer.address, call, amount=amount)
        # TODO (#19): implement gas strategies
        max_gas_price = await self._rpc.eth_gas_price()
        max_tip = min(Amount.gwei(1), max_gas_price)
        nonce = await self._rpc.eth_get_transaction_count(signer.address, BlockLabel.PENDING)
        tx = cast(
            "TransactionDictType",
            unstructure(
                Type2Transaction(
                    chain_id=chain_id,
                    value=amount,
                    gas=gas,
                    max_fee_per_gas=max_gas_price,
                    max_priority_fee_per_gas=max_tip,
                    nonce=nonce,
                    data=call.data_bytes,
                )
            ),
        )
        signed_tx = signer.sign_transaction(tx)
        tx_hash = await self._rpc.eth_send_raw_transaction(signed_tx)
        receipt = await self.wait_for_transaction_receipt(tx_hash)

        if not receipt.succeeded:
            raise TransactionFailed(f"Deploy failed (receipt: {receipt})")

        if receipt.contract_address is None:
            raise BadResponseFormat(
                f"The deploy transaction succeeded, but `contractAddress` is not present "
                f"in the receipt ({receipt})"
            )

        return DeployedContract(call.contract_abi, receipt.contract_address)

    async def broadcast_transact(
        self,
        signer: Signer,
        call: BaseBoundMethodCall,
        amount: None | Amount = None,
        gas: None | int = None,
    ) -> TxHash:
        """
        Broadcasts the transaction without waiting for it to be finalized.
        See :py:meth:`~ClientSession.transact` for the information on the parameters.
        """
        if amount is None:
            amount = Amount(0)

        if not call.mutating:
            raise ValueError("This method is non-mutating, use `eth_call` to invoke it")

        if not call.payable and amount.as_wei() != 0:
            raise ValueError("This method does not accept an associated payment")

        chain_id = await self.chain_id()
        if gas is None:
            gas = await self.estimate_transact(
                signer.address, call, amount=amount, block=BlockLabel.PENDING
            )
        # TODO (#19): implement gas strategies
        max_gas_price = await self._rpc.eth_gas_price()
        max_tip = min(Amount.gwei(1), max_gas_price)
        nonce = await self._rpc.eth_get_transaction_count(signer.address, BlockLabel.PENDING)
        tx = cast(
            "TransactionDictType",
            unstructure(
                Type2Transaction(
                    chain_id=chain_id,
                    to=call.contract_address,
                    value=amount,
                    gas=gas,
                    max_fee_per_gas=max_gas_price,
                    max_priority_fee_per_gas=max_tip,
                    nonce=nonce,
                    data=call.data_bytes,
                )
            ),
        )
        signed_tx = signer.sign_transaction(tx)
        return await self._rpc.eth_send_raw_transaction(signed_tx)

    async def transact(
        self,
        signer: Signer,
        call: BaseBoundMethodCall,
        amount: None | Amount = None,
        gas: None | int = None,
        return_events: None | Sequence[BoundEvent] = None,
    ) -> dict[BoundEvent, list[dict[str, Any]]]:
        """
        Transacts with the contract using a prepared method call.
        If ``gas`` is ``None``, the required amount of gas is estimated first,
        otherwise the provided value is used.
        Waits for the transaction to be confirmed.
        ``amount`` denotes the amount of currency to send with the transaction.

        If any bound events are given in `return_events`, the provider will be queried
        for any firing of these events originating from the hash of the completed transaction
        (from the contract addresses the events are bound to),
        and the results will be returned as a dictionary keyed by the corresponding event object.

        Raises :py:class:`TransactionFailed` if the transaction was submitted successfully,
        but could not be processed.
        If gas estimation is run, see the additional errors that may be raised in the docs for
        :py:meth:`~ClientSession.estimate_transact`.
        """
        tx_hash = await self.broadcast_transact(signer, call, amount=amount, gas=gas)
        receipt = await self.wait_for_transaction_receipt(tx_hash)
        if not receipt.succeeded:
            raise TransactionFailed(f"Transact failed (receipt: {receipt})")

        if return_events is None:
            return {}

        results = {}
        for event in return_events:
            event_filter = event()
            log_entries = await self._rpc.eth_get_logs(
                source=event_filter.contract_address,
                event_filter=EventFilter(event_filter.topics),
                from_block=receipt.block_number,
                to_block=receipt.block_number,
            )
            event_results = []
            for log_entry in log_entries:
                if log_entry.transaction_hash != receipt.transaction_hash:
                    continue

                decoded = event_filter.decode_log_entry(log_entry)
                event_results.append(decoded)

            results[event] = event_results

        return results

    async def iter_blocks(self, poll_interval: int = 1) -> AsyncIterator[BlockHash]:
        """Yields hashes of new blocks being mined."""
        block_filter = await self._rpc.eth_new_block_filter()
        while True:
            block_hashes = await self._rpc.eth_get_filter_changes(block_filter)
            for block_hash in block_hashes:
                # We can't ensure it statically, since `eth_getFilterChanges` return type depends
                # on the filter passed to it.
                yield cast("BlockHash", block_hash)
            await anyio.sleep(poll_interval)

    async def iter_pending_transactions(self, poll_interval: int = 1) -> AsyncIterator[TxHash]:
        """Yields hashes of new transactions being submitted."""
        tx_filter = await self._rpc.eth_new_pending_transaction_filter()
        while True:
            tx_hashes = await self._rpc.eth_get_filter_changes(tx_filter)
            for tx_hash in tx_hashes:
                # We can't ensure it statically, since `eth_getFilterChanges` return type depends
                # on the filter passed to it.
                yield cast("TxHash", tx_hash)
            await anyio.sleep(poll_interval)

    async def iter_events(
        self,
        event_filter: BoundEventFilter,
        poll_interval: int = 1,
        from_block: Block = BlockLabel.LATEST,
        to_block: Block = BlockLabel.LATEST,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Yields decoded log entries produced by the filter.
        The fields that were hashed when converted to topics (that is, fields of reference types)
        are set to ``None``.
        """
        log_filter = await self._rpc.eth_new_filter(
            source=event_filter.contract_address,
            event_filter=EventFilter(event_filter.topics),
            from_block=from_block,
            to_block=to_block,
        )
        while True:
            log_entries = await self._rpc.eth_get_filter_changes(log_filter)
            for log_entry in log_entries:
                # We can't ensure it statically, since `eth_getFilterChanges` return type depends
                # on the filter passed to it.
                yield event_filter.decode_log_entry(cast("LogEntry", log_entry))
            await anyio.sleep(poll_interval)
