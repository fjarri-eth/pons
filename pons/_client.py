from collections.abc import AsyncIterator, Iterable, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, ParamSpec, TypeVar, cast

import anyio
from compages import StructuringError
from ethereum_rpc import (
    JSON,
    Address,
    Amount,
    Block,
    BlockHash,
    BlockInfo,
    BlockLabel,
    EstimateGasParams,
    EthCallParams,
    FilterParams,
    LogEntry,
    RPCError,
    RPCErrorCode,
    TxHash,
    TxInfo,
    TxReceipt,
    Type2Transaction,
    structure,
    unstructure,
)

from ._contract import (
    BoundConstructorCall,
    BoundEvent,
    BoundEventFilter,
    BoundMethodCall,
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
from ._provider import InvalidResponse, Provider, ProviderSession
from ._signer import Signer


@dataclass
class BlockFilter:
    id_: int
    provider_path: tuple[int, ...]


@dataclass
class PendingTransactionFilter:
    id_: int
    provider_path: tuple[int, ...]


@dataclass
class LogFilter:
    id_: int
    provider_path: tuple[int, ...]


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


class RemoteError(Exception):
    """
    A base of all errors occurring on the provider's side.
    Encompasses both errors returned via HTTP status codes
    and the ones returned via the JSON response.
    """


class BadResponseFormat(RemoteError):
    """Raised if the RPC provider returned an unexpectedly formatted response."""


class TransactionFailed(RemoteError):
    """
    Raised if the transaction was submitted successfully,
    but the final receipt indicates a failure.
    """


class ProviderError(RemoteError):
    """A general problem with fulfilling the request at the provider's side."""

    raw_code: int
    """The error code returned by the server."""

    code: None | RPCErrorCode
    """The parsed error code (if known)."""

    message: str
    """The error message."""

    data: None | bytes
    """The associated data (if any)."""

    @classmethod
    def from_rpc_error(cls, exc: RPCError) -> "ProviderError":
        return cls(exc.code, exc.parsed_code, exc.message, exc.data)

    def __init__(
        self, raw_code: int, code: None | RPCErrorCode, message: str, data: None | bytes = None
    ):
        super().__init__(raw_code, code, message, data)
        self.raw_code = raw_code
        self.code = code
        self.message = message
        self.data = data

    def __str__(self) -> str:
        # Substitute the known code if any, or report the raw integer value otherwise
        code = self.code or self.raw_code
        return f"Provider error ({code}): {self.message}" + (
            f" (data: {self.data.hex()})" if self.data else ""
        )


Param = ParamSpec("Param")
RetType = TypeVar("RetType")


@contextmanager
def convert_errors(method_name: str) -> Iterator[None]:
    try:
        yield
    except (StructuringError, InvalidResponse) as exc:
        raise BadResponseFormat(f"{method_name}: {exc}") from exc
    except RPCError as exc:
        raise ProviderError.from_rpc_error(exc) from exc


async def rpc_call(
    provider_session: ProviderSession, method_name: str, ret_type: type[RetType], *args: Any
) -> RetType:
    """Catches various response formatting errors and returns them in a unified way."""
    with convert_errors(method_name):
        result = await provider_session.rpc(method_name, *(unstructure(arg) for arg in args))
        return structure(ret_type, result)


async def rpc_call_pin(
    provider_session: ProviderSession, method_name: str, ret_type: type[RetType], *args: Any
) -> tuple[RetType, tuple[int, ...]]:
    """Catches various response formatting errors and returns them in a unified way."""
    with convert_errors(method_name):
        result, provider_path = await provider_session.rpc_and_pin(
            method_name, *(unstructure(arg) for arg in args)
        )
        return structure(ret_type, result), provider_path


async def rpc_call_at_pin(
    provider_session: ProviderSession,
    provider_path: tuple[int, ...],
    method_name: str,
    ret_type: type[RetType],
    *args: Any,
) -> RetType:
    """Catches various response formatting errors and returns them in a unified way."""
    with convert_errors(method_name):
        result = await provider_session.rpc_at_pin(
            provider_path, method_name, *(unstructure(arg) for arg in args)
        )
        return structure(ret_type, result)


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


class ContractPanic(RemoteError):
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


class ContractLegacyError(RemoteError):
    """A raised Solidity legacy error (from ``require()`` or ``revert()``)."""

    message: str
    """The error message."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ContractError(RemoteError):
    """A raised Solidity error (from ``revert SomeError(...)``)."""

    error: Error
    """The recognized ABI Error object."""

    data: dict[str, Any]
    """The unpacked error data, corresponding to the ABI."""

    def __init__(self, error: Error, decoded_data: dict[str, Any]):
        super().__init__(error, decoded_data)
        self.error = error
        self.data = decoded_data


def decode_contract_error(
    abi: ContractABI, exc: ProviderError
) -> ContractPanic | ContractLegacyError | ContractError | ProviderError:
    # A little wonky, but there's no better way to detect legacy errors without a message.
    # Hopefully these are used very rarely.
    if exc.code == RPCErrorCode.SERVER_ERROR and exc.message == "execution reverted":
        return ContractLegacyError("")
    if exc.code == RPCErrorCode.EXECUTION_ERROR:
        try:
            error, decoded_data = abi.resolve_error(exc.data or b"")
        except UnknownError:
            return exc

        if error == PANIC_ERROR:
            return ContractPanic.from_code(decoded_data["code"])
        if error == LEGACY_ERROR:
            return ContractLegacyError(decoded_data["message"])
        return ContractError(error, decoded_data)
    return exc


class ClientSession:
    """An open session to the provider."""

    def __init__(self, provider_session: ProviderSession):
        self._provider_session = provider_session
        self._net_version: None | str = None
        self._chain_id: None | int = None

    async def net_version(self) -> str:
        """Calls the ``net_version`` RPC method."""
        if self._net_version is None:
            self._net_version = await rpc_call(self._provider_session, "net_version", str)
        return self._net_version

    async def eth_chain_id(self) -> int:
        """Calls the ``eth_chainId`` RPC method."""
        if self._chain_id is None:
            self._chain_id = await rpc_call(self._provider_session, "eth_chainId", int)
        return self._chain_id

    async def eth_get_balance(self, address: Address, block: Block = BlockLabel.LATEST) -> Amount:
        """Calls the ``eth_getBalance`` RPC method."""
        return await rpc_call(self._provider_session, "eth_getBalance", Amount, address, block)

    async def eth_get_transaction_by_hash(self, tx_hash: TxHash) -> None | TxInfo:
        """Calls the ``eth_getTransactionByHash`` RPC method."""
        # Need an explicit cast, mypy doesn't work with union types correctly.
        # See https://github.com/python/mypy/issues/16935
        return cast(
            None | TxInfo,
            await rpc_call(
                self._provider_session,
                "eth_getTransactionByHash",
                None | TxInfo,  # type: ignore[arg-type]
                tx_hash,
            ),
        )

    async def eth_get_transaction_receipt(self, tx_hash: TxHash) -> None | TxReceipt:
        """Calls the ``eth_getTransactionReceipt`` RPC method."""
        # Need an explicit cast, mypy doesn't work with union types correctly.
        # See https://github.com/python/mypy/issues/16935
        return cast(
            None | TxReceipt,
            await rpc_call(
                self._provider_session,
                "eth_getTransactionReceipt",
                None | TxReceipt,  # type: ignore[arg-type]
                tx_hash,
            ),
        )

    async def eth_get_transaction_count(
        self, address: Address, block: Block = BlockLabel.LATEST
    ) -> int:
        """Calls the ``eth_getTransactionCount`` RPC method."""
        return await rpc_call(
            self._provider_session,
            "eth_getTransactionCount",
            int,
            address,
            block,
        )

    async def eth_get_code(self, address: Address, block: Block = BlockLabel.LATEST) -> bytes:
        """Calls the ``eth_getCode`` RPC method."""
        return await rpc_call(self._provider_session, "eth_getCode", bytes, address, block)

    async def eth_get_storage_at(
        self, address: Address, position: int, block: Block = BlockLabel.LATEST
    ) -> bytes:
        """Calls the ``eth_getCode`` RPC method."""
        return await rpc_call(
            self._provider_session,
            "eth_getStorageAt",
            bytes,
            address,
            position,
            block,
        )

    async def wait_for_transaction_receipt(
        self, tx_hash: TxHash, poll_latency: float = 1.0
    ) -> TxReceipt:
        """Queries the transaction receipt waiting for ``poll_latency`` between each attempt."""
        while True:
            receipt = await self.eth_get_transaction_receipt(tx_hash)
            if receipt is not None:
                return receipt
            await anyio.sleep(poll_latency)

    async def eth_call(
        self,
        call: BoundMethodCall,
        block: Block = BlockLabel.LATEST,
        sender_address: None | Address = None,
    ) -> Any:
        """
        Sends a prepared contact method call to the provided address.
        Returns the decoded output.

        If ``sender_address`` is provided, it will be included in the call
        and affect the return value if the method uses ``msg.sender`` internally.
        """
        params = EthCallParams(to=call.contract_address, data=call.data_bytes, from_=sender_address)

        encoded_output = await rpc_call(
            self._provider_session,
            "eth_call",
            bytes,
            params,
            block,
        )
        return call.decode_output(encoded_output)

    async def _eth_send_raw_transaction(self, tx_bytes: bytes) -> TxHash:
        """Sends a signed and serialized transaction."""
        return await rpc_call(self._provider_session, "eth_sendRawTransaction", TxHash, tx_bytes)

    async def _estimate_gas(self, params: EstimateGasParams, block: Block) -> int:
        return await rpc_call(self._provider_session, "eth_estimateGas", int, params, block)

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
        If the error was unknown, falls back to :py:class:`ProviderError`.
        """
        params = EstimateGasParams(
            from_=sender_address, data=call.data_bytes, value=amount or Amount(0)
        )
        try:
            return await self._estimate_gas(params, block)
        except ProviderError as exc:
            raise decode_contract_error(call.contract_abi, exc) from exc

    async def estimate_transfer(
        self,
        source_address: Address,
        destination_address: Address,
        amount: Amount,
        block: Block = BlockLabel.LATEST,
    ) -> int:
        """
        Estimates the amount of gas required to transfer ``amount``.
        Raises a :py:class:`ProviderError` if there is not enough funds in ``source_address``.
        """
        # source_address and amount are optional,
        # but if they are specified, we will fail here instead of later.
        params = EstimateGasParams(from_=source_address, to=destination_address, value=amount)
        return await self._estimate_gas(params, block)

    async def estimate_transact(
        self,
        sender_address: Address,
        call: BoundMethodCall,
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
        If the error was unknown, falls back to :py:class:`ProviderError`.
        """
        params = EstimateGasParams(
            from_=sender_address,
            to=call.contract_address,
            data=call.data_bytes,
            value=amount or Amount(0),
        )
        try:
            return await self._estimate_gas(params, block)
        except ProviderError as exc:
            raise decode_contract_error(call.contract_abi, exc) from exc

    async def eth_gas_price(self) -> Amount:
        """Calls the ``eth_gasPrice`` RPC method."""
        return await rpc_call(self._provider_session, "eth_gasPrice", Amount)

    async def eth_block_number(self) -> int:
        """Calls the ``eth_blockNumber`` RPC method."""
        return await rpc_call(self._provider_session, "eth_blockNumber", int)

    async def eth_get_block_by_hash(
        self, block_hash: BlockHash, *, with_transactions: bool = False
    ) -> None | BlockInfo:
        """Calls the ``eth_getBlockByHash`` RPC method."""
        # Need an explicit cast, mypy doesn't work with union types correctly.
        # See https://github.com/python/mypy/issues/16935
        return cast(
            None | BlockInfo,
            await rpc_call(
                self._provider_session,
                "eth_getBlockByHash",
                None | BlockInfo,  # type: ignore[arg-type]
                block_hash,
                with_transactions,
            ),
        )

    async def eth_get_block_by_number(
        self, block: Block = BlockLabel.LATEST, *, with_transactions: bool = False
    ) -> None | BlockInfo:
        """Calls the ``eth_getBlockByNumber`` RPC method."""
        # Need an explicit cast, mypy doesn't work with union types correctly.
        # See https://github.com/python/mypy/issues/16935
        return cast(
            None | BlockInfo,
            await rpc_call(
                self._provider_session,
                "eth_getBlockByNumber",
                None | BlockInfo,  # type: ignore[arg-type]
                block,
                with_transactions,
            ),
        )

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
        chain_id = await self.eth_chain_id()
        if gas is None:
            gas = await self.estimate_transfer(signer.address, destination_address, amount)
        # TODO (#19): implement gas strategies
        max_gas_price = await self.eth_gas_price()
        max_tip = min(Amount.gwei(1), max_gas_price)
        nonce = await self.eth_get_transaction_count(signer.address, BlockLabel.PENDING)
        tx = cast(
            dict[str, JSON],
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
        return await self._eth_send_raw_transaction(signed_tx)

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

        chain_id = await self.eth_chain_id()
        if gas is None:
            gas = await self.estimate_deploy(signer.address, call, amount=amount)
        # TODO (#19): implement gas strategies
        max_gas_price = await self.eth_gas_price()
        max_tip = min(Amount.gwei(1), max_gas_price)
        nonce = await self.eth_get_transaction_count(signer.address, BlockLabel.PENDING)
        tx = cast(
            dict[str, JSON],
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
        tx_hash = await self._eth_send_raw_transaction(signed_tx)
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
        call: BoundMethodCall,
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

        chain_id = await self.eth_chain_id()
        if gas is None:
            gas = await self.estimate_transact(
                signer.address, call, amount=amount, block=BlockLabel.PENDING
            )
        # TODO (#19): implement gas strategies
        max_gas_price = await self.eth_gas_price()
        max_tip = min(Amount.gwei(1), max_gas_price)
        nonce = await self.eth_get_transaction_count(signer.address, BlockLabel.PENDING)
        tx = cast(
            dict[str, JSON],
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
        return await self._eth_send_raw_transaction(signed_tx)

    async def transact(
        self,
        signer: Signer,
        call: BoundMethodCall,
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
            log_entries = await self.eth_get_logs(
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

    async def eth_get_logs(
        self,
        source: None | Address | Iterable[Address] = None,
        event_filter: None | EventFilter = None,
        from_block: Block = BlockLabel.LATEST,
        to_block: Block = BlockLabel.LATEST,
    ) -> tuple[LogEntry, ...]:
        """Calls the ``eth_getLogs`` RPC method."""
        if isinstance(source, Iterable):
            source = tuple(source)
        params = FilterParams(
            from_block=from_block,
            to_block=to_block,
            address=source,
            topics=event_filter.topics if event_filter is not None else None,
        )
        return await rpc_call(self._provider_session, "eth_getLogs", tuple[LogEntry, ...], params)

    async def eth_new_block_filter(self) -> BlockFilter:
        """Calls the ``eth_newBlockFilter`` RPC method."""
        result, provider_path = await rpc_call_pin(
            self._provider_session, "eth_newBlockFilter", int
        )
        return BlockFilter(id_=result, provider_path=provider_path)

    async def eth_new_pending_transaction_filter(self) -> PendingTransactionFilter:
        """Calls the ``eth_newPendingTransactionFilter`` RPC method."""
        result, provider_path = await rpc_call_pin(
            self._provider_session, "eth_newPendingTransactionFilter", int
        )
        return PendingTransactionFilter(id_=result, provider_path=provider_path)

    async def eth_new_filter(
        self,
        source: None | Address | Iterable[Address] = None,
        event_filter: None | EventFilter = None,
        from_block: Block = BlockLabel.LATEST,
        to_block: Block = BlockLabel.LATEST,
    ) -> LogFilter:
        """Calls the ``eth_newFilter`` RPC method."""
        if isinstance(source, Iterable):
            source = tuple(source)
        params = FilterParams(
            from_block=from_block,
            to_block=to_block,
            address=source,
            topics=event_filter.topics if event_filter is not None else None,
        )
        result, provider_path = await rpc_call_pin(
            self._provider_session, "eth_newFilter", int, params
        )
        return LogFilter(id_=result, provider_path=provider_path)

    async def _query_filter(
        self, method_name: str, filter_: BlockFilter | PendingTransactionFilter | LogFilter
    ) -> tuple[BlockHash, ...] | tuple[TxHash, ...] | tuple[LogEntry, ...]:
        if isinstance(filter_, BlockFilter):
            return await rpc_call_at_pin(
                self._provider_session,
                filter_.provider_path,
                method_name,
                tuple[BlockHash, ...],
                filter_.id_,
            )
        if isinstance(filter_, PendingTransactionFilter):
            return await rpc_call_at_pin(
                self._provider_session,
                filter_.provider_path,
                method_name,
                tuple[TxHash, ...],
                filter_.id_,
            )
        return await rpc_call_at_pin(
            self._provider_session,
            filter_.provider_path,
            method_name,
            tuple[LogEntry, ...],
            filter_.id_,
        )

    async def eth_get_filter_logs(
        self, filter_: BlockFilter | PendingTransactionFilter | LogFilter
    ) -> tuple[BlockHash, ...] | tuple[TxHash, ...] | tuple[LogEntry, ...]:
        """Calls the ``eth_getFilterLogs`` RPC method."""
        return await self._query_filter("eth_getFilterLogs", filter_)

    async def eth_get_filter_changes(
        self, filter_: BlockFilter | PendingTransactionFilter | LogFilter
    ) -> tuple[BlockHash, ...] | tuple[TxHash, ...] | tuple[LogEntry, ...]:
        """
        Calls the ``eth_getFilterChanges`` RPC method.
        Depending on what ``filter_`` was, returns a tuple of corresponding results.
        """
        return await self._query_filter("eth_getFilterChanges", filter_)

    async def iter_blocks(self, poll_interval: int = 1) -> AsyncIterator[BlockHash]:
        """Yields hashes of new blocks being mined."""
        block_filter = await self.eth_new_block_filter()
        while True:
            block_hashes = await self.eth_get_filter_changes(block_filter)
            for block_hash in block_hashes:
                # We can't ensure it statically, since `eth_getFilterChanges` return type depends
                # on the filter passed to it.
                yield cast(BlockHash, block_hash)
            await anyio.sleep(poll_interval)

    async def iter_pending_transactions(self, poll_interval: int = 1) -> AsyncIterator[TxHash]:
        """Yields hashes of new transactions being submitted."""
        tx_filter = await self.eth_new_pending_transaction_filter()
        while True:
            tx_hashes = await self.eth_get_filter_changes(tx_filter)
            for tx_hash in tx_hashes:
                # We can't ensure it statically, since `eth_getFilterChanges` return type depends
                # on the filter passed to it.
                yield cast(TxHash, tx_hash)
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
        log_filter = await self.eth_new_filter(
            source=event_filter.contract_address,
            event_filter=EventFilter(event_filter.topics),
            from_block=from_block,
            to_block=to_block,
        )
        while True:
            log_entries = await self.eth_get_filter_changes(log_filter)
            for log_entry in log_entries:
                # We can't ensure it statically, since `eth_getFilterChanges` return type depends
                # on the filter passed to it.
                yield event_filter.decode_log_entry(cast(LogEntry, log_entry))
            await anyio.sleep(poll_interval)
