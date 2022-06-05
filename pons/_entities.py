from abc import ABC, abstractmethod
from functools import cached_property
from enum import Enum
from typing import NamedTuple, Union, Optional, Tuple, Type, TypeVar

from eth_utils import to_checksum_address, to_canonical_address

from ._provider import ResponseDict


class RPCDecodingError(Exception):
    """
    Raised on an error when decoding a value in an RPC response.
    """


TypedDataLike = TypeVar("TypedDataLike", bound="TypedData")


TypedQuantityLike = TypeVar("TypedQuantityLike", bound="TypedQuantity")


class TypedData(ABC):
    def __init__(self, value: bytes):
        if not isinstance(value, bytes):
            raise TypeError(
                f"{self.__class__.__name__} must be a bytestring, got {type(value).__name__}"
            )
        if len(value) != self._length():
            raise ValueError(
                f"{self.__class__.__name__} must be {self._length()} bytes long, got {len(value)}"
            )
        self._value = value

    @abstractmethod
    def _length(self) -> int:
        ...

    def rpc_encode(self) -> str:
        return rpc_encode_data(self._value)

    @classmethod
    def rpc_decode(cls: Type[TypedDataLike], val: str) -> TypedDataLike:
        try:
            return cls(rpc_decode_data(val))
        except ValueError as exc:
            raise RPCDecodingError(str(exc)) from exc

    def __bytes__(self):
        return self._value

    def __hash__(self):
        return hash(self._value)

    def _check_type(self, other):
        if type(self) != type(other):
            raise TypeError(f"Incompatible types: {type(self).__name__} and {type(other).__name__}")

    def __eq__(self, other):
        self._check_type(other)
        return self._value == other._value

    def __repr__(self):
        return f'{self.__class__.__name__}(bytes.fromhex("{self._value.hex()}"))'


class TypedQuantity:
    def __init__(self, value: int):
        if not isinstance(value, int):
            raise TypeError(
                f"{self.__class__.__name__} must be an integer, got {type(value).__name__}"
            )
        if value < 0:
            raise ValueError(f"{self.__class__.__name__} must be non-negative, got {value}")
        self._value = value

    def rpc_encode(self) -> str:
        return rpc_encode_quantity(self._value)

    @classmethod
    def rpc_decode(cls: Type[TypedQuantityLike], val: str) -> TypedQuantityLike:
        # `rpc_decode_quantity` will raise RPCDecodingError on any error,
        # and if it succeeds, constructor won't raise anything -
        # the value is already guaranteed to be `int` and non-negative
        return cls(rpc_decode_quantity(val))

    def __hash__(self):
        return hash(self._value)

    def _check_type(self, other):
        if type(self) != type(other):
            raise TypeError(f"Incompatible types: {type(self).__name__} and {type(other).__name__}")

    def __eq__(self, other):
        self._check_type(other)
        return self._value == other._value

    def __repr__(self):
        return f"{self.__class__.__name__}({self._value})"


class Amount(TypedQuantity):
    """
    Represents a sum in the chain's native currency.

    Can be subclassed to represent specific currencies of different networks (ETH, MATIC etc).
    Arithmetic and comparison methods perform strict type checking,
    so different currency objects cannot be compared or added to each other.
    """

    @classmethod
    def wei(cls, value: int) -> "Amount":
        """
        Creates a sum from the amount in wei (``10^(-18)`` of the main unit).
        """
        return cls(value)

    @classmethod
    def gwei(cls, value: Union[int, float]) -> "Amount":
        """
        Creates a sum from the amount in gwei (``10^(-9)`` of the main unit).
        """
        return cls(int(10**9 * value))

    @classmethod
    def ether(cls, value: Union[int, float]) -> "Amount":
        """
        Creates a sum from the amount in the main currency unit.
        """
        return cls(int(10**18 * value))

    def as_wei(self) -> int:
        """
        Returns the amount in wei.
        """
        return self._value

    def as_gwei(self) -> float:
        """
        Returns the amount in gwei.
        """
        return self._value / 10**9

    def as_ether(self) -> float:
        """
        Returns the amount in the main currency unit.
        """
        return self._value / 10**18

    def __add__(self, other):
        self._check_type(other)
        return self.wei(self._value + other._value)

    def __sub__(self, other):
        self._check_type(other)
        return self.wei(self._value - other._value)

    def __mul__(self, other: int):
        if not isinstance(other, int):
            raise TypeError(f"Expected an integer, got {type(other).__name__}")
        return self.wei(self._value * other)

    def __floordiv__(self, other: int):
        if not isinstance(other, int):
            raise TypeError(f"Expected an integer, got {type(other).__name__}")
        return self.wei(self._value // other)

    def __gt__(self, other):
        self._check_type(other)
        return self._value > other._value

    def __ge__(self, other):
        self._check_type(other)
        return self._value >= other._value

    def __lt__(self, other):
        self._check_type(other)
        return self._value < other._value

    def __le__(self, other):
        self._check_type(other)
        return self._value <= other._value


class Address(TypedData):
    """
    Represents an Ethereum address.
    """

    def _length(self):
        return 20

    @classmethod
    def from_hex(cls, address_str: str) -> "Address":
        """
        Creates the address from a hex representation
        (with or without the ``0x`` prefix, checksummed or not).
        """
        return cls(to_canonical_address(address_str))

    @cached_property
    def checksum(self) -> str:
        """
        Retunrs the checksummed hex representation of the address.
        """
        return to_checksum_address(self._value)

    def rpc_encode(self) -> str:
        # Overriding the base class method to encode into a checksummed address -
        # some providers require it.
        return self.checksum

    def __str__(self):
        return self.checksum

    def __repr__(self):
        return f"{self.__class__.__name__}.from_hex({self.checksum})"


class Block(Enum):
    """
    Block aliases supported by Ethereum RPC.
    """

    LATEST = "latest"
    """The latest confirmed block"""

    EARLIEST = "earliest"
    """The earliest block"""

    PENDING = "pending"
    """Currently pending block"""


class BlockFilter(TypedQuantity):
    """
    A block filter identifier (returned by ``eth_newBlockFilter``).
    """


class PendingTransactionFilter(TypedQuantity):
    """
    A pending transaction filter identifier (returned by ``eth_newPendingTransactionFilter``).
    """


class LogFilter(TypedQuantity):
    """
    A log filter identifier (returned by ``eth_newFilter``).
    """


class LogTopic(TypedData):
    """
    A log topic for log filtering.
    """

    def _length(self):
        return 32


class BlockHash(TypedData):
    """
    A wrapper for the block hash.
    """

    def _length(self):
        return 32


class TxHash(TypedData):
    """
    A wrapper for the transaction hash.
    """

    def _length(self):
        return 32


class TxInfo(NamedTuple):
    """
    Transaction info.
    """

    # TODO: make an enum?
    type: int
    """Transaction type: 0 for legacy transactions, 2 for EIP1559 transactions."""

    hash: TxHash
    """Transaction hash."""

    block_hash: BlockHash
    """The hash of the block this transaction belongs to."""

    block_number: int
    """The number of the block this transaction belongs to."""

    transaction_index: int
    """Transaction index."""

    from_: Address
    """Transaction sender."""

    to: Optional[Address]
    """
    Transaction recipient.
    ``None`` when it's a contract creation transaction.
    """

    value: Amount
    """Associated funds."""

    nonce: int
    """Transaction nonce."""

    gas: int
    """Gas used by the transaction."""

    gas_price: Amount
    """Gas price used by the transaction."""

    # TODO: we may want to have a separate derived class for EIP1559 transactions,
    # but for now this will do.

    max_fee_per_gas: Optional[Amount]
    """``maxFeePerGas`` value specified by the sender. Only for EIP1559 transactions."""

    max_priority_fee_per_gas: Optional[Amount]
    """``maxPriorityFeePerGas`` value specified by the sender. Only for EIP1559 transactions."""

    @classmethod
    def rpc_decode(cls, val: ResponseDict) -> "TxInfo":
        max_fee_per_gas = Amount.rpc_decode(val["maxFeePerGas"]) if "maxFeePerGas" in val else None
        max_priority_fee_per_gas = (
            Amount.rpc_decode(val["maxPriorityFeePerGas"])
            if "maxPriorityFeePerGas" in val
            else None
        )
        return cls(
            type=rpc_decode_quantity(val["type"]),
            hash=TxHash.rpc_decode(val["hash"]),
            block_hash=BlockHash.rpc_decode(val["blockHash"]),
            block_number=rpc_decode_quantity(val["blockNumber"]),
            transaction_index=rpc_decode_quantity(val["transactionIndex"]),
            from_=Address.rpc_decode(val["from"]),
            to=Address.rpc_decode(val["to"]) if val["to"] else None,
            value=Amount.rpc_decode(val["value"]),
            nonce=rpc_decode_quantity(val["nonce"]),
            max_fee_per_gas=max_fee_per_gas,
            max_priority_fee_per_gas=max_priority_fee_per_gas,
            gas=rpc_decode_quantity(val["gas"]),
            gas_price=Amount.rpc_decode(val["gasPrice"]),
        )


class BlockInfo(NamedTuple):
    """
    Block info.
    """

    number: int
    """Block number."""

    hash: BlockHash
    """Block hash."""

    parent_hash: BlockHash
    """Parent block's hash."""

    nonce: int
    """Block's nonce."""

    miner: Address
    """Block's miner."""

    difficulty: int
    """Block's difficulty."""

    total_difficulty: int
    """Block's totat difficulty."""

    size: int
    """Block size."""

    gas_limit: int
    """Block's gas limit."""

    gas_used: int
    """Gas used for the block."""

    base_fee_per_gas: Amount
    """Base fee per gas in this block."""

    timestamp: int
    """Block's timestamp."""

    transaction_hashes: Tuple[TxHash, ...]
    """A list of transaction hashes in this block."""

    transactions: Optional[Tuple[TxInfo, ...]]
    """
    A list of details of transactions in this block.
    Only present if it was requested.
    """

    @classmethod
    def rpc_decode(cls, val: ResponseDict) -> "BlockInfo":
        transactions: Optional[Tuple[TxInfo, ...]]
        transaction_hashes: Tuple[TxHash, ...]
        if len(val["transactions"]) == 0:
            transactions = ()
            transaction_hashes = ()
        elif isinstance(val["transactions"][0], str):
            transactions = None
            transaction_hashes = tuple(
                TxHash.rpc_decode(tx_hash) for tx_hash in val["transactions"]
            )
        else:
            transactions = tuple(TxInfo.rpc_decode(tx_info) for tx_info in val["transactions"])
            transaction_hashes = tuple(tx.hash for tx in transactions)

        return cls(
            number=rpc_decode_quantity(val["number"]),
            hash=BlockHash.rpc_decode(val["hash"]),
            parent_hash=BlockHash.rpc_decode(val["parentHash"]),
            nonce=rpc_decode_quantity(val["nonce"]),
            difficulty=rpc_decode_quantity(val["difficulty"]),
            total_difficulty=rpc_decode_quantity(val["totalDifficulty"]),
            size=rpc_decode_quantity(val["size"]),
            gas_limit=rpc_decode_quantity(val["gasLimit"]),
            gas_used=rpc_decode_quantity(val["gasUsed"]),
            base_fee_per_gas=Amount.rpc_decode(val["baseFeePerGas"]),
            timestamp=rpc_decode_quantity(val["timestamp"]),
            miner=Address.rpc_decode(val["miner"]),
            transactions=transactions,
            transaction_hashes=transaction_hashes,
        )


class TxReceipt(NamedTuple):
    """
    Transaction receipt.
    """

    block_hash: BlockHash
    """Hash of the block including this transaction."""

    block_number: int
    """Block number including this transaction."""

    contract_address: Optional[Address]
    """
    If it was a successful deployment transaction,
    contains the address of the deployed contract.
    """

    cumulative_gas_used: int
    """The total amount of gas used when this transaction was executed in the block."""

    effective_gas_price: Amount
    """The actual value per gas deducted from the sender's account."""

    from_: Address
    """Address of the sender."""

    gas_used: int
    """The amount of gas used by the transaction."""

    to: Optional[Address]
    """
    Address of the receiver.
    ``None`` when the transaction is a contract creation transaction.
    """

    transaction_hash: TxHash
    """Hash of the transaction."""

    transaction_index: int
    """Integer of the transaction's index position in the block."""

    # TODO: make an enum?
    type: int
    """Transaction type: 0 for legacy transactions, 2 for EIP1559 transactions."""

    succeeded: bool
    """Whether the transaction was successful."""

    @classmethod
    def rpc_decode(cls, val: ResponseDict) -> "TxReceipt":
        contract_address = val["contractAddress"]
        return cls(
            block_hash=BlockHash.rpc_decode(val["blockHash"]),
            block_number=rpc_decode_quantity(val["blockNumber"]),
            contract_address=Address.rpc_decode(contract_address) if contract_address else None,
            cumulative_gas_used=rpc_decode_quantity(val["cumulativeGasUsed"]),
            effective_gas_price=Amount.rpc_decode(val["effectiveGasPrice"]),
            from_=Address.rpc_decode(val["from"]),
            gas_used=rpc_decode_quantity(val["gasUsed"]),
            to=Address.rpc_decode(val["to"]) if val["to"] else None,
            transaction_hash=TxHash.rpc_decode(val["transactionHash"]),
            transaction_index=rpc_decode_quantity(val["transactionIndex"]),
            type=rpc_decode_quantity(val["type"]),
            succeeded=(rpc_decode_quantity(val["status"]) == 1),
        )


class LogEntry(NamedTuple):
    """
    Log entry metadata.
    """

    removed: bool
    """
    ``True`` if log was removed, due to a chain reorganization.
    ``False`` if it is a valid log.
    """

    address: Address
    """
    The contract address from which this log originated.
    """

    data: bytes
    """ABI-packed non-indexed arguments of the event."""

    topics: Tuple[LogTopic, ...]
    """
    Values of indexed event fields.
    For a named event, the first topic is the event's selector.
    """

    # In the docs of major providers (Infura, Alchemy, Quicknode) it is claimed
    # that the following fields can be null if "it is a pending log".
    # I could not reproduce such behavior, so for now they're staying non-nullable.

    log_index: int
    """Log's position in the block."""

    transaction_index: int
    """Transaction's position in the block."""

    transaction_hash: TxHash
    """Hash of the transactions this log was created from."""

    block_hash: BlockHash
    """Hash of the block where this log was in."""

    block_number: int
    """The block number where this log was."""

    @classmethod
    def rpc_decode(cls, val: ResponseDict) -> "LogEntry":
        return cls(
            removed=val["removed"],
            log_index=rpc_decode_quantity(val["logIndex"]),
            transaction_index=rpc_decode_quantity(val["transactionIndex"]),
            transaction_hash=TxHash.rpc_decode(val["transactionHash"]),
            block_hash=BlockHash.rpc_decode(val["blockHash"]),
            block_number=rpc_decode_quantity(val["blockNumber"]),
            address=Address.rpc_decode(val["address"]),
            data=rpc_decode_data(val["data"]),
            topics=tuple(LogTopic.rpc_decode(topic) for topic in val["topics"]),
        )


def rpc_encode_quantity(val: int) -> str:
    return hex(val)


def rpc_encode_data(val: bytes) -> str:
    return "0x" + val.hex()


def rpc_encode_block(val: Union[int, Block]) -> str:
    if isinstance(val, Block):
        return val.value
    else:
        return rpc_encode_quantity(val)


def rpc_decode_quantity(val: str) -> int:
    if not isinstance(val, str):
        raise RPCDecodingError("Encoded quantity must be a string")
    if not val.startswith("0x"):
        raise RPCDecodingError("Encoded quantity must start with `0x`")
    try:
        return int(val, 16)
    except ValueError as exc:
        raise RPCDecodingError(f"Could not convert encoded quantity to an integer: {exc}") from exc


def rpc_decode_data(val: str) -> bytes:
    if not isinstance(val, str):
        raise RPCDecodingError("Encoded data must be a string")
    if not val.startswith("0x"):
        raise RPCDecodingError("Encoded data must start with `0x`")
    try:
        return bytes.fromhex(val[2:])
    except ValueError as exc:
        raise RPCDecodingError(f"Could not convert encoded data to bytes: {exc}") from exc


def rpc_decode_block(val: str) -> Union[int, str]:
    try:
        Block(val)  # check if it's one of the enum's values
        return val
    except ValueError:
        pass

    return rpc_decode_quantity(val)
