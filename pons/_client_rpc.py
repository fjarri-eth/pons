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
        """Calls the ``net_version`` RPC method."""
        return await rpc_call(self._provider_session, "net_version", str)

    async def eth_chain_id(self) -> int:
        """Calls the ``eth_chainId`` RPC method."""
        return await rpc_call(self._provider_session, "eth_chainId", int)

    async def eth_get_balance(self, address: Address, block: Block = BlockLabel.LATEST) -> Amount:
        """Calls the ``eth_getBalance`` RPC method."""
        return await rpc_call(self._provider_session, "eth_getBalance", Amount, address, block)

    async def eth_get_transaction_by_hash(self, tx_hash: TxHash) -> None | TxInfo:
        """Calls the ``eth_getTransactionByHash`` RPC method."""
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
        """Calls the ``eth_getTransactionReceipt`` RPC method."""
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

    async def eth_call(
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
        """Sends a signed and serialized transaction."""
        return await rpc_call(self._provider_session, "eth_sendRawTransaction", TxHash, tx_bytes)

    async def eth_estimate_gas(self, params: EstimateGasParams, block: Block) -> int:
        """Calls the ``eth_estimateGas`` RPC method."""
        return await rpc_call(self._provider_session, "eth_estimateGas", int, params, block)

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
        """Calls the ``eth_getBlockByNumber`` RPC method."""
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
        return BlockFilter(id=result, provider_path=provider_path)

    async def eth_new_pending_transaction_filter(self) -> PendingTransactionFilter:
        """Calls the ``eth_newPendingTransactionFilter`` RPC method."""
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

    async def eth_uninstall_filter(
        self, filter_: BlockFilter | PendingTransactionFilter | LogFilter
    ) -> bool:
        """
        Calls the ``eth_uninstallFilter`` RPC method.
        Returns ``true`` if there was an active filter with a given filter ID.

        .. note::

            Many providers will automatically uninstall filters after some time.
        """
        return await rpc_call_at_pin(
            self._provider_session, filter_.provider_path, "eth_uninstallFilter", bool, filter_.id
        )

    async def web3_client_version(self) -> str:
        """Calls the ``web3_clientVersion`` RPC method."""
        return await rpc_call(self._provider_session, "web3_clientVersion", str)

    async def web3_sha3(self, data: bytes) -> bytes:
        """Calls the ``web3_sha3`` RPC method."""
        return await rpc_call(self._provider_session, "web3_sha3", bytes, data)

    async def net_listening(self) -> bool:
        """Calls the ``net_listening`` RPC method."""
        return await rpc_call(self._provider_session, "net_listening", bool)

    async def net_peer_count(self) -> int:
        """Calls the ``net_peerCount`` RPC method."""
        return await rpc_call(self._provider_session, "net_peerCount", int)

    async def eth_coinbase(self) -> Address:
        """Calls the ``eth_coinbase`` RPC method."""
        return await rpc_call(self._provider_session, "eth_coinbase", Address)

    async def eth_accounts(self) -> list[Address]:
        """Calls the ``eth_accounts`` RPC method."""
        return await rpc_call(self._provider_session, "eth_accounts", list[Address])

    async def eth_get_block_transaction_count_by_hash(self, block_hash: BlockHash) -> int:
        """Calls the ``eth_getBlockTransactionCountByHash`` RPC method."""
        return await rpc_call(
            self._provider_session, "eth_getBlockTransactionCountByHash", int, block_hash
        )

    async def eth_get_block_transaction_count_by_number(self, block: Block) -> int:
        """Calls the ``eth_getBlockTransactionCountByNumber`` RPC method."""
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
        """Calls the ``eth_getTransactionByBlockHashAndIndex`` RPC method."""
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
        """Calls the ``eth_getTransactionByBlockNumberAndIndex`` RPC method."""
        return await rpc_call(
            self._provider_session, "eth_getTransactionByBlockNumberAndIndex", TxInfo, block, index
        )

    async def eth_get_uncle_by_block_hash_and_index(
        self, block_hash: BlockHash, index: int
    ) -> None | BlockInfo:
        """Calls the ``eth_getUncleByBlockHashAndIndex`` RPC method."""
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
        """Calls the ``eth_getUncleByBlockNumberAndIndex`` RPC method."""
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
