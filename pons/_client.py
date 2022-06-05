from contextlib import asynccontextmanager
from enum import Enum
from functools import wraps
from typing import Union, Any, Optional, AsyncIterator, Iterable, Dict, List, Tuple

import anyio

from ._contract import (
    DeployedContract,
    BoundConstructorCall,
    BoundReadCall,
    BoundWriteCall,
    BoundEventFilter,
)
from ._contract_abi import EventFilter, PANIC_ERROR, LEGACY_ERROR, UnknownError, ContractABI, Error
from ._provider import (
    Provider,
    ProviderSession,
    UnexpectedResponse,
    RPCError,
    ResponseDict,
)
from ._signer import Signer
from ._entities import (
    Address,
    Amount,
    Block,
    BlockFilter,
    PendingTransactionFilter,
    LogFilter,
    LogEntry,
    BlockHash,
    TxHash,
    BlockInfo,
    TxReceipt,
    TxInfo,
    rpc_encode_quantity,
    rpc_encode_data,
    rpc_encode_block,
    rpc_decode_quantity,
    rpc_decode_data,
    RPCDecodingError,
)


class Client:
    """
    An Ethereum RPC client.
    """

    def __init__(self, provider: Provider):
        self._provider = provider
        self._net_version: Optional[str] = None
        self._chain_id: Optional[int] = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator["ClientSession"]:
        """
        Opens a session to the client allowing the backend to optimize sequential requests.
        """
        async with self._provider.session() as provider_session:
            client_session = ClientSession(provider_session)
            yield client_session
            # TODO: incorporate cached values from the session back into the client


class RemoteError(Exception):
    """
    A base of all errors occurring on the provider's side.
    Encompasses both errors returned via HTTP status codes
    and the ones returned via the JSON response.
    """


class BadResponseFormat(RemoteError):
    """
    Raised if the RPC provider returned an unexpectedly formatted response.
    """


class TransactionFailed(RemoteError):
    """
    Raised if the transaction was submitted successfully,
    but the final receipt indicates a failure.
    """


class ProviderErrorCode(Enum):
    """
    Known RPC error codes returned by providers.
    """

    # This is our placeholder value, shouldn't be encountered in a remote server response
    UNKNOWN_REASON = 0
    """An error code whose description is not present in this enum."""

    SERVER_ERROR = -32000
    """Reserved for implementation-defined server-errors. See the message for details."""

    EXECUTION_ERROR = 3
    """Contract transaction failed during execution. See the data for details."""

    @classmethod
    def from_int(cls, val: int) -> "ProviderErrorCode":
        try:
            return cls(val)
        except ValueError:
            return cls.UNKNOWN_REASON


class ProviderError(RemoteError):
    """
    A general problem with fulfilling the request at the provider's side.
    """

    Code = ProviderErrorCode

    raw_code: int
    """The error code returned by the server."""

    code: ProviderErrorCode
    """The parsed error code."""

    message: str
    """The error message."""

    data: Optional[bytes]
    """The associated data (if any)."""

    @classmethod
    def from_rpc_error(cls, exc: RPCError) -> "ProviderError":
        data = rpc_decode_data(exc.data) if exc.data else None
        parsed_code = ProviderErrorCode.from_int(exc.code)
        return cls(exc.code, parsed_code, exc.message, data)

    def __init__(
        self, raw_code: int, code: ProviderErrorCode, message: str, data: Optional[bytes] = None
    ):
        super().__init__(raw_code, code, message, data)
        self.raw_code = raw_code
        self.code = code
        self.message = message
        self.data = data

    def __str__(self):
        # Substitute the known code if any, or report the raw integer value otherwise
        code = self.raw_code if self.code == ProviderErrorCode.UNKNOWN_REASON else self.code.name
        return f"Provider error ({code}): {self.message}" + (
            f" (data: {self.data.hex()})" if self.data else ""
        )


def rpc_call(method_name):
    """
    Catches various response formatting errors and returns them in a unified way.
    """

    def _wrapper(func):
        @wraps(func)
        async def _wrapped(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
            except (RPCDecodingError, UnexpectedResponse) as exc:
                raise BadResponseFormat(f"{method_name}: {exc}") from exc
            except RPCError as exc:
                raise ProviderError.from_rpc_error(exc) from exc
            return result

        return _wrapped

    return _wrapper


class ContractPanicReason(Enum):
    """
    Reasons leading to a contract call panicking.
    """

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
    """
    A panic raised in a contract call.
    """

    Reason = ContractPanicReason

    reason: ContractPanicReason
    """Parsed panic reason."""

    @classmethod
    def from_code(cls, code: int):
        return cls(ContractPanicReason.from_int(code))

    def __init__(self, reason: ContractPanicReason):
        super().__init__(reason)
        self.reason = reason


class ContractLegacyError(RemoteError):
    """
    A raised Solidity legacy error (from ``require()`` or ``revert()``).
    """

    message: str
    """The error message."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ContractError(RemoteError):
    """
    A raised Solidity error (from ``revert SomeError(...)``).
    """

    error: Error
    """The recognized ABI Error object."""

    data: Dict[str, Any]
    """The unpacked error data, corresponding to the ABI."""

    def __init__(self, error: Error, decoded_data: Dict[str, Any]):
        super().__init__(error, decoded_data)
        self.error = error
        self.data = decoded_data


def decode_contract_error(
    abi: ContractABI, exc: ProviderError
) -> Union[ContractPanic, ContractLegacyError, ContractError, ProviderError]:
    # A little wonky, but there's no better way to detect legacy errors without a message.
    # Hopefully these are used very rarely.
    if exc.code == ProviderErrorCode.SERVER_ERROR and exc.message == "execution reverted":
        return ContractLegacyError("")
    elif exc.code == ProviderErrorCode.EXECUTION_ERROR:
        try:
            error, decoded_data = abi.resolve_error(exc.data or b"")
        except UnknownError:
            return exc

        if error == PANIC_ERROR:
            return ContractPanic.from_code(decoded_data["code"])
        elif error == LEGACY_ERROR:
            return ContractLegacyError(decoded_data["message"])
        else:
            return ContractError(error, decoded_data)
    else:
        return exc


class ClientSession:
    """
    An open session to the provider.
    """

    def __init__(self, provider_session: ProviderSession):
        self._provider_session = provider_session
        self._net_version: Optional[str] = None
        self._chain_id: Optional[int] = None

    @rpc_call("net_version")
    async def net_version(self) -> str:
        """
        Calls the ``net_version`` RPC method.
        """
        if self._net_version is None:
            result = await self._provider_session.rpc("net_version")
            if not isinstance(result, str):
                raise RPCDecodingError("expected a string result")
            self._net_version = result
        return self._net_version

    @rpc_call("eth_chainId")
    async def eth_chain_id(self) -> int:
        """
        Calls the ``eth_chainId`` RPC method.
        """
        if self._chain_id is None:
            result = await self._provider_session.rpc("eth_chainId")
            self._chain_id = rpc_decode_quantity(result)
        return self._chain_id

    @rpc_call("eth_getBalance")
    async def eth_get_balance(
        self, address: Address, block: Union[int, Block] = Block.LATEST
    ) -> Amount:
        """
        Calls the ``eth_getBalance`` RPC method.
        """
        result = await self._provider_session.rpc(
            "eth_getBalance", address.rpc_encode(), rpc_encode_block(block)
        )
        return Amount.rpc_decode(result)

    @rpc_call("eth_getTransactionByHash")
    async def eth_get_transaction_by_hash(self, tx_hash: TxHash) -> Optional[TxInfo]:
        """
        Calls the ``eth_getTransactionByHash`` RPC method.
        """
        result = await self._provider_session.rpc_dict(
            "eth_getTransactionByHash", tx_hash.rpc_encode()
        )
        if not result:
            return None
        return TxInfo.rpc_decode(result)

    @rpc_call("eth_getTransactionReceipt")
    async def eth_get_transaction_receipt(self, tx_hash: TxHash) -> Optional[TxReceipt]:
        """
        Calls the ``eth_getTransactionReceipt`` RPC method.
        """
        result = await self._provider_session.rpc_dict(
            "eth_getTransactionReceipt", tx_hash.rpc_encode()
        )
        if not result:
            return None
        return TxReceipt.rpc_decode(result)

    @rpc_call("eth_getTransactionCount")
    async def eth_get_transaction_count(
        self, address: Address, block: Union[int, Block] = Block.LATEST
    ) -> int:
        """
        Calls the ``eth_getTransactionCount`` RPC method.
        """
        result = await self._provider_session.rpc(
            "eth_getTransactionCount", address.rpc_encode(), rpc_encode_block(block)
        )
        return rpc_decode_quantity(result)

    async def wait_for_transaction_receipt(
        self, tx_hash: TxHash, poll_latency: float = 1.0
    ) -> TxReceipt:
        """
        Queries the transaction receipt waiting for ``poll_latency`` between each attempt.
        """
        while True:
            receipt = await self.eth_get_transaction_receipt(tx_hash)
            if receipt:
                return receipt
            await anyio.sleep(poll_latency)

    @rpc_call("eth_call")
    async def eth_call(self, call: BoundReadCall, block: Union[int, Block] = Block.LATEST) -> Any:
        """
        Sends a prepared contact method call to the provided address.
        Returns the decoded output.
        """
        result = await self._provider_session.rpc(
            "eth_call",
            {
                "to": call.contract_address.rpc_encode(),
                "data": rpc_encode_data(call.data_bytes),
            },
            rpc_encode_block(block),
        )

        encoded_output = rpc_decode_data(result)
        return call.decode_output(encoded_output)

    @rpc_call("eth_sendRawTransaction")
    async def _eth_send_raw_transaction(self, tx_bytes: bytes) -> TxHash:
        """
        Sends a signed and serialized transaction.
        """
        result = await self._provider_session.rpc(
            "eth_sendRawTransaction", rpc_encode_data(tx_bytes)
        )
        return TxHash.rpc_decode(result)

    @rpc_call("eth_estimateGas")
    async def _estimate_gas(self, tx: dict):
        result = await self._provider_session.rpc(
            "eth_estimateGas", tx, rpc_encode_block(Block.LATEST)
        )
        return rpc_decode_quantity(result)

    async def estimate_deploy(self, call: BoundConstructorCall, amount: Amount = Amount(0)) -> int:
        """
        Estimates the amount of gas required to deploy the contract with the given args.

        Raises :py:class:`ContractPanic`, :py:class:`ContractLegacyError`,
        or :py:class`ContractError` if a known error was caught during the dry run.
        If the error was unknown, falls back to :py:class:`ProviderError`.
        """
        tx = {
            "data": rpc_encode_data(call.data_bytes),
            "value": amount.rpc_encode(),
        }
        try:
            return await self._estimate_gas(tx)
        except ProviderError as exc:
            raise decode_contract_error(call.contract_abi, exc) from exc

    async def estimate_transfer(
        self, source_address: Address, destination_address: Address, amount: Amount
    ) -> int:
        """
        Estimates the amount of gas required to transfer ``amount``.
        Raises a :py:class:`ProviderError` if there is not enough funds in ``source_address``.
        """
        # source_address and amount are optional,
        # but if they are specified, we will fail here instead of later.
        tx = {
            "from": source_address.rpc_encode(),
            "to": destination_address.rpc_encode(),
            "value": amount.rpc_encode(),
        }
        return await self._estimate_gas(tx)

    async def estimate_transact(self, call: BoundWriteCall, amount: Amount = Amount(0)) -> int:
        """
        Estimates the amount of gas required to transact with a contract.

        Raises :py:class:`ContractPanic`, :py:class:`ContractLegacyError`,
        or :py:class`ContractError` if a known error was caught during the dry run.
        If the error was unknown, falls back to :py:class:`ProviderError`.
        """
        tx = {
            "to": call.contract_address.rpc_encode(),
            "data": rpc_encode_data(call.data_bytes),
            "value": amount.rpc_encode(),
        }
        try:
            return await self._estimate_gas(tx)
        except ProviderError as exc:
            raise decode_contract_error(call.contract_abi, exc) from exc

    @rpc_call("eth_gasPrice")
    async def eth_gas_price(self) -> Amount:
        """
        Calls the ``eth_gasPrice`` RPC method.
        """
        result = await self._provider_session.rpc("eth_gasPrice")
        return Amount.rpc_decode(result)

    @rpc_call("eth_blockNumber")
    async def eth_block_number(self) -> int:
        """
        Calls the ``eth_blockNumber`` RPC method.
        """
        result = await self._provider_session.rpc("eth_blockNumber")
        return rpc_decode_quantity(result)

    @rpc_call("eth_getBlockByHash")
    async def eth_get_block_by_hash(
        self, block_hash: BlockHash, with_transactions: bool = False
    ) -> Optional[BlockInfo]:
        """
        Calls the ``eth_getBlockByHash`` RPC method.
        """
        result = await self._provider_session.rpc_dict(
            "eth_getBlockByHash", block_hash.rpc_encode(), with_transactions
        )
        if result is None:
            return None
        return BlockInfo.rpc_decode(result)

    @rpc_call("eth_getBlockByNumber")
    async def eth_get_block_by_number(
        self, block: Union[int, Block] = Block.LATEST, with_transactions: bool = False
    ) -> Optional[BlockInfo]:
        """
        Calls the ``eth_getBlockByNumber`` RPC method.
        """
        result = await self._provider_session.rpc_dict(
            "eth_getBlockByNumber", rpc_encode_block(block), with_transactions
        )
        if result is None:
            return None
        return BlockInfo.rpc_decode(result)

    async def broadcast_transfer(
        self,
        signer: Signer,
        destination_address: Address,
        amount: Amount,
        gas: Optional[int] = None,
    ) -> TxHash:
        """
        Broadcasts the fund transfer transaction, but does not wait for it to be processed.
        If ``gas`` is ``None``, the required amount of gas is estimated first,
        otherwise the provided value is used.
        """
        chain_id = await self.eth_chain_id()
        if gas is None:
            gas = await self.estimate_transfer(signer.address, destination_address, amount)
        # TODO: implement gas strategies
        max_gas_price = await self.eth_gas_price()
        max_tip = Amount.gwei(1)
        nonce = await self.eth_get_transaction_count(signer.address, Block.LATEST)
        tx = {
            "type": 2,  # EIP-2930 transaction
            "chainId": rpc_encode_quantity(chain_id),
            "to": destination_address.rpc_encode(),
            "value": amount.rpc_encode(),
            "gas": rpc_encode_quantity(gas),
            "maxFeePerGas": max_gas_price.rpc_encode(),
            "maxPriorityFeePerGas": max_tip.rpc_encode(),
            "nonce": rpc_encode_quantity(nonce),
        }
        signed_tx = signer.sign_transaction(tx)
        return await self._eth_send_raw_transaction(signed_tx)

    async def transfer(
        self,
        signer: Signer,
        destination_address: Address,
        amount: Amount,
        gas: Optional[int] = None,
    ):
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
        amount: Amount = Amount(0),
        gas: Optional[int] = None,
    ) -> DeployedContract:
        """
        Deploys the contract passing ``args`` to the constructor.
        If ``gas`` is ``None``, the required amount of gas is estimated first,
        otherwise the provided value is used.
        Waits for the transaction to be confirmed.

        Raises :py:class:`TransactionFailed` if the transaction was submitted successfully,
        but could not be processed.
        If gas estimation is run, see the additional errors that may be raised in the docs for
        :py:meth:`~ClientSession.estimate_deploy`.
        """
        if not call.payable and amount.as_wei() != 0:
            raise ValueError("This constructor does not accept an associated payment")

        chain_id = await self.eth_chain_id()
        if gas is None:
            gas = await self.estimate_deploy(call, amount=amount)
        # TODO: implement gas strategies
        max_gas_price = await self.eth_gas_price()
        max_tip = Amount.gwei(1)
        nonce = await self.eth_get_transaction_count(signer.address, Block.LATEST)
        tx = {
            "type": 2,  # EIP-2930 transaction
            "chainId": rpc_encode_quantity(chain_id),
            "value": amount.rpc_encode(),
            "gas": rpc_encode_quantity(gas),
            "maxFeePerGas": max_gas_price.rpc_encode(),
            "maxPriorityFeePerGas": max_tip.rpc_encode(),
            "nonce": rpc_encode_quantity(nonce),
            "data": rpc_encode_data(call.data_bytes),
        }
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
        call: BoundWriteCall,
        amount: Amount = Amount(0),
        gas: Optional[int] = None,
    ) -> TxHash:
        if not call.payable and amount.as_wei() != 0:
            raise ValueError("This method does not accept an associated payment")

        chain_id = await self.eth_chain_id()
        if gas is None:
            gas = await self.estimate_transact(call, amount=amount)
        # TODO: implement gas strategies
        max_gas_price = await self.eth_gas_price()
        max_tip = Amount.gwei(1)
        nonce = await self.eth_get_transaction_count(signer.address, Block.LATEST)
        tx = {
            "type": 2,  # EIP-2930 transaction
            "chainId": rpc_encode_quantity(chain_id),
            "to": call.contract_address.rpc_encode(),
            "value": amount.rpc_encode(),
            "gas": rpc_encode_quantity(gas),
            "maxFeePerGas": max_gas_price.rpc_encode(),
            "maxPriorityFeePerGas": max_tip.rpc_encode(),
            "nonce": rpc_encode_quantity(nonce),
            "data": rpc_encode_data(call.data_bytes),
        }
        signed_tx = signer.sign_transaction(tx)
        return await self._eth_send_raw_transaction(signed_tx)

    async def transact(
        self,
        signer: Signer,
        call: BoundWriteCall,
        amount: Amount = Amount(0),
        gas: Optional[int] = None,
    ):
        """
        Transacts with the contract using a prepared method call.
        If ``gas`` is ``None``, the required amount of gas is estimated first,
        otherwise the provided value is used.
        Waits for the transaction to be confirmed.

        Raises :py:class:`TransactionFailed` if the transaction was submitted successfully,
        but could not be processed.
        If gas estimation is run, see the additional errors that may be raised in the docs for
        :py:meth:`~ClientSession.estimate_transact`.
        """
        tx_hash = await self.broadcast_transact(signer, call, amount=amount, gas=gas)
        receipt = await self.wait_for_transaction_receipt(tx_hash)
        if not receipt.succeeded:
            raise TransactionFailed(f"Transact failed (receipt: {receipt})")

    @rpc_call("eth_newBlockFilter")
    async def eth_new_block_filter(self) -> BlockFilter:
        """
        Calls the ``eth_newBlockFilter`` RPC method.
        """
        result = await self._provider_session.rpc("eth_newBlockFilter")
        return BlockFilter.rpc_decode(result)

    @rpc_call("eth_newPendingTransactionFilter")
    async def eth_new_pending_transaction_filter(self) -> PendingTransactionFilter:
        """
        Calls the ``eth_newPendingTransactionFilter`` RPC method.
        """
        result = await self._provider_session.rpc("eth_newPendingTransactionFilter")
        return PendingTransactionFilter.rpc_decode(result)

    @rpc_call("eth_newFilter")
    async def eth_new_filter(
        self,
        source: Optional[Union[Address, Iterable[Address]]] = None,
        event_filter: Optional[EventFilter] = None,
        from_block: Union[int, Block] = Block.LATEST,
        to_block: Union[int, Block] = Block.LATEST,
    ) -> LogFilter:
        """
        Calls the ``eth_newFilter`` RPC method.
        """
        params: Dict[str, Any] = {
            "fromBlock": rpc_encode_block(from_block),
            "toBlock": rpc_encode_block(to_block),
        }
        if isinstance(source, Address):
            params["address"] = source.rpc_encode()
        elif source:
            params["address"] = [address.rpc_encode() for address in source]
        if event_filter:
            encoded_topics: List[Optional[List[str]]] = []
            for topic in event_filter.topics:
                if topic is None:
                    encoded_topics.append(None)
                else:
                    encoded_topics.append([elem.rpc_encode() for elem in topic])
            params["topics"] = encoded_topics

        result = await self._provider_session.rpc("eth_newFilter", params)
        return LogFilter.rpc_decode(result)

    @rpc_call("eth_getFilterChangers")
    async def eth_get_filter_changes(
        self, filter_: Union[BlockFilter, PendingTransactionFilter, LogFilter]
    ) -> Union[Tuple[BlockHash, ...], Tuple[TxHash, ...], Tuple[LogEntry, ...]]:
        """
        Calls the ``eth_getFilterChangers`` RPC method.
        Depending on what ``filter_`` was, returns a tuple of corresponding results.
        """
        results = await self._provider_session.rpc("eth_getFilterChanges", filter_.rpc_encode())

        if isinstance(filter_, BlockFilter):
            return tuple(BlockHash.rpc_decode(elem) for elem in results)
        elif isinstance(filter_, PendingTransactionFilter):
            return tuple(TxHash.rpc_decode(elem) for elem in results)
        else:
            return tuple(LogEntry.rpc_decode(ResponseDict(elem)) for elem in results)

    async def iter_blocks(self, poll_interval: int = 1) -> AsyncIterator[BlockHash]:
        """
        Yields hashes of new blocks being mined.
        """
        block_filter = await self.eth_new_block_filter()
        while True:
            block_hashes = await self.eth_get_filter_changes(block_filter)
            for block_hash in block_hashes:
                yield block_hash
            await anyio.sleep(poll_interval)

    async def iter_pending_transactions(self, poll_interval: int = 1) -> AsyncIterator[TxHash]:
        """
        Yields hashes of new transactions being submitted.
        """
        tx_filter = await self.eth_new_pending_transaction_filter()
        while True:
            tx_hashes = await self.eth_get_filter_changes(tx_filter)
            for tx_hash in tx_hashes:
                yield tx_hash
            await anyio.sleep(poll_interval)

    async def iter_events(
        self,
        event_filter: BoundEventFilter,
        poll_interval: int = 1,
        from_block: Union[int, Block] = Block.LATEST,
        to_block: Union[int, Block] = Block.LATEST,
    ) -> AsyncIterator[Dict[str, Any]]:
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
                yield event_filter.decode_log_entry(log_entry)
            await anyio.sleep(poll_interval)
