from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from compages import StructuringError
from ethereum_rpc import (
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
    TxHash,
    TxInfo,
    TxReceipt,
    structure,
    unstructure,
)

from ._contract import BaseBoundMethodCall
from ._contract_abi import EventFilter
from ._provider import ProviderPath, ProviderSession


@dataclass
class BlockFilter:
    """
    A block filter created on a remote provider.

    Expires after some time subject to the provider's settings.
    """

    id: int
    provider_path: ProviderPath


@dataclass
class PendingTransactionFilter:
    """
    A pending transaction filter created on a remote provider.

    Expires after some time subject to the provider's settings.
    """

    id: int
    provider_path: ProviderPath


@dataclass
class LogFilter:
    """
    A log filter created on a remote provider.

    Expires after some time subject to the provider's settings.
    """

    id: int
    provider_path: ProviderPath


class BadResponseFormat(Exception):
    """Raised if the RPC provider returned an unexpectedly formatted response."""


@contextmanager
def convert_errors(method_name: str) -> Iterator[None]:
    try:
        yield
    except StructuringError as exc:
        raise BadResponseFormat(f"{method_name}: {exc}") from exc


RetType = TypeVar("RetType")


async def rpc_call(
    provider_session: ProviderSession, method_name: str, ret_type: type[RetType], *args: Any
) -> RetType:
    """Catches various response formatting errors and returns them in a unified way."""
    with convert_errors(method_name):
        result = await provider_session.rpc(method_name, *(unstructure(arg) for arg in args))
        return structure(ret_type, result)


async def rpc_call_pin(
    provider_session: ProviderSession, method_name: str, ret_type: type[RetType], *args: Any
) -> tuple[RetType, ProviderPath]:
    """Catches various response formatting errors and returns them in a unified way."""
    with convert_errors(method_name):
        result, provider_path = await provider_session.rpc_and_pin(
            method_name, *(unstructure(arg) for arg in args)
        )
        return structure(ret_type, result), provider_path


async def rpc_call_at_pin(
    provider_session: ProviderSession,
    provider_path: ProviderPath,
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


class ClientSessionRPC:
    """
    The hub for methods which directly correspond to Ethereum RPC calls.

    The methods of this class may raise
    :py:class:`ProviderError` (coming from the lower level)
    or :py:class:`BadResponseFormat` (failed to deserialize the response into the expected type).
    """

    def __init__(self, provider_session: ProviderSession):
        self._provider_session = provider_session

    async def net_version(self) -> str:
        """Returns the current network id."""
        return await rpc_call(self._provider_session, "net_version", str)

    async def eth_chain_id(self) -> int:
        """Returns the chain ID used for signing replay-protected transactions."""
        return await rpc_call(self._provider_session, "eth_chainId", int)

    async def eth_get_balance(self, address: Address, block: Block = BlockLabel.LATEST) -> Amount:
        """Returns the balance of the account of given address."""
        return await rpc_call(self._provider_session, "eth_getBalance", Amount, address, block)

    async def eth_get_transaction_by_hash(self, tx_hash: TxHash) -> None | TxInfo:
        """Returns the information about a transaction requested by transaction hash."""
        # Need an explicit cast, mypy doesn't work with union types correctly.
        # See https://github.com/python/mypy/issues/16935
        return cast(
            "None | TxInfo",
            await rpc_call(
                self._provider_session,
                "eth_getTransactionByHash",
                None | TxInfo,  # type: ignore[arg-type]
                tx_hash,
            ),
        )

    async def eth_get_transaction_receipt(self, tx_hash: TxHash) -> None | TxReceipt:
        """
        Returns the receipt of a transaction by transaction hash.

        .. note::

            That the receipt is not available for pending transactions.
        """
        # Need an explicit cast, mypy doesn't work with union types correctly.
        # See https://github.com/python/mypy/issues/16935
        return cast(
            "None | TxReceipt",
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
        """Returns the number of transactions sent from an address."""
        return await rpc_call(
            self._provider_session,
            "eth_getTransactionCount",
            int,
            address,
            block,
        )

    async def eth_get_code(self, address: Address, block: Block = BlockLabel.LATEST) -> bytes:
        """Returns code at a given address."""
        return await rpc_call(self._provider_session, "eth_getCode", bytes, address, block)

    async def eth_get_storage_at(
        self, address: Address, position: int, block: Block = BlockLabel.LATEST
    ) -> bytes:
        """Returns the value from a storage position at a given address."""
        return await rpc_call(
            self._provider_session,
            "eth_getStorageAt",
            bytes,
            address,
            position,
            block,
        )

    async def eth_call(
        self,
        call: BaseBoundMethodCall,
        block: Block = BlockLabel.LATEST,
        sender_address: None | Address = None,
    ) -> Any:
        """
        Executes a new message call immediately without creating a transaction on the blockchain.
        Often used for executing read-only smart contract functions,
        for example the ``balanceOf`` for an ERC-20 contract.

        If ``sender_address`` is provided, it will be included in the call
        and affect the return value if the method uses ``msg.sender`` internally.

        The decoded output is returned according to :py:class:`Method.decode_output` rules.
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

    async def eth_send_raw_transaction(self, tx_bytes: bytes) -> TxHash:
        """Creates new message call transaction or a contract creation for signed transactions."""
        return await rpc_call(self._provider_session, "eth_sendRawTransaction", TxHash, tx_bytes)

    async def eth_estimate_gas(self, params: EstimateGasParams, block: Block) -> int:
        """
        Generates and returns an estimate of how much gas is necessary
        to allow the transaction to complete.
        The transaction will not be added to the blockchain.
        Note that the estimate may be significantly more than the amount of gas
        actually used by the transaction, for a variety of reasons
        including EVM mechanics and node performance.
        """
        return await rpc_call(self._provider_session, "eth_estimateGas", int, params, block)

    async def eth_gas_price(self) -> Amount:
        """
        Returns an estimate of the current price per gas in wei,
        according to a provider-specific algorithm.
        """
        return await rpc_call(self._provider_session, "eth_gasPrice", Amount)

    async def eth_block_number(self) -> int:
        """Returns the number of the most recent block."""
        return await rpc_call(self._provider_session, "eth_blockNumber", int)

    async def eth_get_block_by_hash(
        self, block_hash: BlockHash, *, with_transactions: bool = False
    ) -> None | BlockInfo:
        """Returns information about a block by hash."""
        # Need an explicit cast, mypy doesn't work with union types correctly.
        # See https://github.com/python/mypy/issues/16935
        return cast(
            "None | BlockInfo",
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
        """Returns information about a block by block number."""
        # Need an explicit cast, mypy doesn't work with union types correctly.
        # See https://github.com/python/mypy/issues/16935
        return cast(
            "None | BlockInfo",
            await rpc_call(
                self._provider_session,
                "eth_getBlockByNumber",
                None | BlockInfo,  # type: ignore[arg-type]
                block,
                with_transactions,
            ),
        )

    async def eth_get_logs(
        self,
        source: None | Address | Iterable[Address] = None,
        event_filter: None | EventFilter = None,
        from_block: Block = BlockLabel.LATEST,
        to_block: Block = BlockLabel.LATEST,
    ) -> tuple[LogEntry, ...]:
        """Returns an array of all logs matching a given filter object."""
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
        """Creates a filter in the node, to notify when a new block arrives."""
        result, provider_path = await rpc_call_pin(
            self._provider_session, "eth_newBlockFilter", int
        )
        return BlockFilter(id=result, provider_path=provider_path)

    async def eth_new_pending_transaction_filter(self) -> PendingTransactionFilter:
        """Creates a filter in the node, to notify when new pending transactions arrive."""
        result, provider_path = await rpc_call_pin(
            self._provider_session, "eth_newPendingTransactionFilter", int
        )
        return PendingTransactionFilter(id=result, provider_path=provider_path)

    async def eth_new_filter(
        self,
        source: None | Address | Iterable[Address] = None,
        event_filter: None | EventFilter = None,
        from_block: Block = BlockLabel.LATEST,
        to_block: Block = BlockLabel.LATEST,
    ) -> LogFilter:
        """
        Creates a filter object, based on filter options,
        to notify when the state changes (logs).
        """
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
        return LogFilter(id=result, provider_path=provider_path)

    async def _query_filter(
        self, method_name: str, filter_: BlockFilter | PendingTransactionFilter | LogFilter
    ) -> tuple[BlockHash, ...] | tuple[TxHash, ...] | tuple[LogEntry, ...]:
        if isinstance(filter_, BlockFilter):
            return await rpc_call_at_pin(
                self._provider_session,
                filter_.provider_path,
                method_name,
                tuple[BlockHash, ...],
                filter_.id,
            )
        if isinstance(filter_, PendingTransactionFilter):
            return await rpc_call_at_pin(
                self._provider_session,
                filter_.provider_path,
                method_name,
                tuple[TxHash, ...],
                filter_.id,
            )
        return await rpc_call_at_pin(
            self._provider_session,
            filter_.provider_path,
            method_name,
            tuple[LogEntry, ...],
            filter_.id,
        )

    async def eth_get_filter_logs(
        self, filter_: BlockFilter | PendingTransactionFilter | LogFilter
    ) -> tuple[BlockHash, ...] | tuple[TxHash, ...] | tuple[LogEntry, ...]:
        """Returns an array of all logs matching filter with given id."""
        return await self._query_filter("eth_getFilterLogs", filter_)

    async def eth_get_filter_changes(
        self, filter_: BlockFilter | PendingTransactionFilter | LogFilter
    ) -> tuple[BlockHash, ...] | tuple[TxHash, ...] | tuple[LogEntry, ...]:
        """
        Polling method for a filter, which returns an array of logs which occurred since last poll.

        Depending on what ``filter_`` was, returns a tuple of corresponding results.
        """
        return await self._query_filter("eth_getFilterChanges", filter_)

    async def eth_uninstall_filter(
        self, filter_: BlockFilter | PendingTransactionFilter | LogFilter
    ) -> bool:
        """
        Uninstalls a filter with given id. Should always be called when watch is no longer needed.

        Returns ``true`` if there was an active filter with a given filter ID.

        .. note::

            Many providers will automatically uninstall filters after some time
            if they are not queried.
        """
        return await rpc_call_at_pin(
            self._provider_session, filter_.provider_path, "eth_uninstallFilter", bool, filter_.id
        )

    async def web3_client_version(self) -> str:
        """Returns the current client version."""
        return await rpc_call(self._provider_session, "web3_clientVersion", str)

    async def web3_sha3(self, data: bytes) -> bytes:
        """Returns Keccak-256 (*not* the standardized SHA3-256) of the given data."""
        return await rpc_call(self._provider_session, "web3_sha3", bytes, data)

    async def net_listening(self) -> bool:
        """Returns ``True`` if client is actively listening for network connections."""
        return await rpc_call(self._provider_session, "net_listening", bool)

    async def net_peer_count(self) -> int:
        """Returns number of peers currently connected to the client."""
        return await rpc_call(self._provider_session, "net_peerCount", int)

    async def eth_coinbase(self) -> Address:
        """Returns the client coinbase address."""
        return await rpc_call(self._provider_session, "eth_coinbase", Address)

    async def eth_accounts(self) -> list[Address]:
        """Returns a list of addresses owned by client."""
        return await rpc_call(self._provider_session, "eth_accounts", list[Address])

    async def eth_get_block_transaction_count_by_hash(self, block_hash: BlockHash) -> int:
        """
        Returns the number of transactions in a block from a block
        matching the given block hash.
        """
        return await rpc_call(
            self._provider_session, "eth_getBlockTransactionCountByHash", int, block_hash
        )

    async def eth_get_block_transaction_count_by_number(self, block: Block) -> int:
        """Returns the number of transactions in a block matching the given block number."""
        return await rpc_call(
            self._provider_session, "eth_getBlockTransactionCountByNumber", int, block
        )

    async def eth_get_uncle_count_by_block_hash(self, block_hash: BlockHash) -> int:
        """Returns the number of uncles in a block from a block matching the given block hash."""
        return await rpc_call(
            self._provider_session, "eth_getUncleCountByBlockHash", int, block_hash
        )

    async def eth_get_uncle_count_by_block_number(self, block: Block) -> int:
        """Returns the number of uncles in a block from a block matching the given block number."""
        return await rpc_call(self._provider_session, "eth_getUncleCountByBlockNumber", int, block)

    async def eth_get_transaction_by_block_hash_and_index(
        self, block_hash: BlockHash, index: int
    ) -> TxInfo:
        """Returns information about a transaction by block hash and transaction index position."""
        return await rpc_call(
            self._provider_session,
            "eth_getTransactionByBlockHashAndIndex",
            TxInfo,
            block_hash,
            index,
        )

    async def eth_get_transaction_by_block_number_and_index(
        self, block: Block, index: int
    ) -> TxInfo:
        """
        Returns information about a transaction by block number
        and transaction index position.
        """
        return await rpc_call(
            self._provider_session, "eth_getTransactionByBlockNumberAndIndex", TxInfo, block, index
        )

    async def eth_get_uncle_by_block_hash_and_index(
        self, block_hash: BlockHash, index: int
    ) -> None | BlockInfo:
        """Returns information about a uncle of a block by hash and uncle index position."""
        # Need an explicit cast, mypy doesn't work with union types correctly.
        # See https://github.com/python/mypy/issues/16935
        return cast(
            "None | BlockInfo",
            await rpc_call(
                self._provider_session,
                "eth_getUncleByBlockHashAndIndex",
                None | BlockInfo,  # type: ignore[arg-type]
                block_hash,
                index,
            ),
        )

    async def eth_get_uncle_by_block_number_and_index(
        self, block: Block, index: int
    ) -> None | BlockInfo:
        """Returns information about a uncle of a block by number and uncle index position."""
        # Need an explicit cast, mypy doesn't work with union types correctly.
        # See https://github.com/python/mypy/issues/16935
        return cast(
            "None | BlockInfo",
            await rpc_call(
                self._provider_session,
                "eth_getUncleByBlockNumberAndIndex",
                None | BlockInfo,  # type: ignore[arg-type]
                block,
                index,
            ),
        )
