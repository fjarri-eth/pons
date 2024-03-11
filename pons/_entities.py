from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from typing import Any, NewType, TypeVar, cast

from eth_utils import to_canonical_address, to_checksum_address

TypedDataLike = TypeVar("TypedDataLike", bound="TypedData")


TypedQuantityLike = TypeVar("TypedQuantityLike", bound="TypedQuantity")


class TypedData(ABC):
    def __init__(self, value: bytes):
        self._value = value
        if not isinstance(value, bytes):
            raise TypeError(
                f"{self.__class__.__name__} must be a bytestring, got {type(value).__name__}"
            )
        if len(value) != self._length():
            raise ValueError(
                f"{self.__class__.__name__} must be {self._length()} bytes long, got {len(value)}"
            )

    @abstractmethod
    def _length(self) -> int:
        """Returns the length of this type's values representation in bytes."""

    def __bytes__(self) -> bytes:
        return self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def _check_type(self: TypedDataLike, other: Any) -> TypedDataLike:
        if type(self) != type(other):
            raise TypeError(f"Incompatible types: {type(self).__name__} and {type(other).__name__}")
        return cast(TypedDataLike, other)

    def __eq__(self, other: object) -> bool:
        return self._value == self._check_type(other)._value

    def __repr__(self) -> str:
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

    def __hash__(self) -> int:
        return hash(self._value)

    def __int__(self) -> int:
        return self._value

    def _check_type(self: TypedQuantityLike, other: Any) -> TypedQuantityLike:
        if type(self) != type(other):
            raise TypeError(f"Incompatible types: {type(self).__name__} and {type(other).__name__}")
        return cast(TypedQuantityLike, other)

    def __eq__(self, other: object) -> bool:
        return self._value == self._check_type(other)._value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._value})"


# This is force-documented as :py:class in ``api.rst``
# because Sphinx cannot resolve typevars correctly.
# See https://github.com/sphinx-doc/sphinx/issues/9705
CustomAmount = TypeVar("CustomAmount", bound="Amount")
"""A subclass of :py:class:`Amount`."""


class Amount(TypedQuantity):
    """
    Represents a sum in the chain's native currency.

    Can be subclassed to represent specific currencies of different networks (ETH, MATIC etc).
    Arithmetic and comparison methods perform strict type checking,
    so different currency objects cannot be compared or added to each other.
    """

    @classmethod
    def wei(cls: type[CustomAmount], value: int) -> CustomAmount:
        """Creates a sum from the amount in wei (``10^(-18)`` of the main unit)."""
        return cls(value)

    @classmethod
    def gwei(cls: type[CustomAmount], value: float) -> CustomAmount:
        """Creates a sum from the amount in gwei (``10^(-9)`` of the main unit)."""
        return cls(int(10**9 * value))

    @classmethod
    def ether(cls: type[CustomAmount], value: float) -> CustomAmount:
        """Creates a sum from the amount in the main currency unit."""
        return cls(int(10**18 * value))

    def as_wei(self) -> int:
        """Returns the amount in wei."""
        return self._value

    def as_gwei(self) -> float:
        """Returns the amount in gwei."""
        return self._value / 10**9

    def as_ether(self) -> float:
        """Returns the amount in the main currency unit."""
        return self._value / 10**18

    def __add__(self: CustomAmount, other: Any) -> CustomAmount:
        return self.wei(self._value + self._check_type(other)._value)

    def __sub__(self: CustomAmount, other: Any) -> CustomAmount:
        return self.wei(self._value - self._check_type(other)._value)

    def __mul__(self: CustomAmount, other: int) -> CustomAmount:
        if not isinstance(other, int):
            raise TypeError(f"Expected an integer, got {type(other).__name__}")
        return self.wei(self._value * other)

    def __floordiv__(self: CustomAmount, other: int) -> CustomAmount:
        if not isinstance(other, int):
            raise TypeError(f"Expected an integer, got {type(other).__name__}")
        return self.wei(self._value // other)

    def __gt__(self, other: Any) -> bool:
        return self._value > self._check_type(other)._value

    def __ge__(self, other: Any) -> bool:
        return self._value >= self._check_type(other)._value

    def __lt__(self, other: Any) -> bool:
        return self._value < self._check_type(other)._value

    def __le__(self, other: Any) -> bool:
        return self._value <= self._check_type(other)._value


# This is force-documented as :py:class in ``api.rst``
# because Sphinx cannot resolve typevars correctly.
# See https://github.com/sphinx-doc/sphinx/issues/9705
CustomAddress = TypeVar("CustomAddress", bound="Address")
"""A subclass of :py:class:`Address`."""


class Address(TypedData):
    """Represents an Ethereum address."""

    def _length(self) -> int:
        return 20

    @classmethod
    def from_hex(cls: type[CustomAddress], address_str: str) -> CustomAddress:
        """
        Creates the address from a hex representation
        (with or without the ``0x`` prefix, checksummed or not).
        """
        return cls(to_canonical_address(address_str))

    @cached_property
    def checksum(self) -> str:
        """Retunrs the checksummed hex representation of the address."""
        return to_checksum_address(self._value)

    def __str__(self) -> str:
        return self.checksum

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}.from_hex({self.checksum})"


class Block(Enum):
    """Block aliases supported by Ethereum RPC."""

    LATEST = "latest"
    """The latest confirmed block"""

    EARLIEST = "earliest"
    """The earliest block"""

    PENDING = "pending"
    """Currently pending block"""

    SAFE = "safe"
    """The latest safe head block"""

    FINALIZED = "finalized"
    """The latest finalized block"""


class BlockFilterId(TypedQuantity):
    """A block filter identifier (returned by ``eth_newBlockFilter``)."""


class PendingTransactionFilterId(TypedQuantity):
    """A pending transaction filter identifier (returned by ``eth_newPendingTransactionFilter``)."""


class LogFilterId(TypedQuantity):
    """A log filter identifier (returned by ``eth_newFilter``)."""


@dataclass
class BlockFilter:
    id_: BlockFilterId
    provider_path: tuple[int, ...]


@dataclass
class PendingTransactionFilter:
    id_: PendingTransactionFilterId
    provider_path: tuple[int, ...]


@dataclass
class LogFilter:
    id_: LogFilterId
    provider_path: tuple[int, ...]


class LogTopic(TypedData):
    """A log topic for log filtering."""

    def _length(self) -> int:
        return 32


class BlockHash(TypedData):
    """A wrapper for the block hash."""

    def _length(self) -> int:
        return 32


class TxHash(TypedData):
    """A wrapper for the transaction hash."""

    def _length(self) -> int:
        return 32


@dataclass
class TxInfo:
    """Transaction info."""

    # TODO: make an enum?
    type_: int
    """Transaction type: 0 for legacy transactions, 2 for EIP1559 transactions."""

    hash_: TxHash
    """Transaction hash."""

    input_: None | bytes
    """The data sent along with the transaction."""

    block_hash: None | BlockHash
    """The hash of the block this transaction belongs to. ``None`` for pending transactions."""

    block_number: int
    """The number of the block this transaction belongs to. May be a pending block."""

    transaction_index: None | int
    """Transaction index. ``None`` for pending transactions."""

    from_: Address
    """Transaction sender."""

    to: None | Address
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

    max_fee_per_gas: None | Amount
    """``maxFeePerGas`` value specified by the sender. Only for EIP1559 transactions."""

    max_priority_fee_per_gas: None | Amount
    """``maxPriorityFeePerGas`` value specified by the sender. Only for EIP1559 transactions."""


@dataclass
class BlockInfo:
    """Block info."""

    number: int
    """Block number."""

    hash_: None | BlockHash
    """Block hash. ``None`` for pending blocks."""

    parent_hash: BlockHash
    """Parent block's hash."""

    nonce: None | int
    """Block's nonce. ``None`` for pending blocks."""

    miner: None | Address
    """Block's miner. ``None`` for pending blocks."""

    difficulty: int
    """Block's difficulty."""

    total_difficulty: None | int
    """Block's totat difficulty. ``None`` for pending blocks."""

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

    transactions: tuple[TxInfo, ...] | tuple[TxHash, ...]
    """
    A list of transaction hashes in this block, or a list of details of transactions in this block,
    depending on what was requested.
    """


@dataclass
class LogEntry:
    """Log entry metadata."""

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

    topics: tuple[LogTopic, ...]
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


@dataclass
class TxReceipt:
    """Transaction receipt."""

    block_hash: BlockHash
    """Hash of the block including this transaction."""

    block_number: int
    """Block number including this transaction."""

    contract_address: None | Address
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

    to: None | Address
    """
    Address of the receiver.
    ``None`` when the transaction is a contract creation transaction.
    """

    transaction_hash: TxHash
    """Hash of the transaction."""

    transaction_index: int
    """Integer of the transaction's index position in the block."""

    # TODO: make an enum?
    type_: int
    """Transaction type: 0 for legacy transactions, 2 for EIP1559 transactions."""

    status: int
    """1 if the transaction was successful, 0 otherwise."""

    logs: tuple[LogEntry, ...]
    """An array of log objects generated by this transaction."""

    @property
    def succeeded(self) -> bool:
        """``True`` if the transaction succeeded."""
        return self.status == 1


class RPCErrorCode(Enum):
    """Known RPC error codes returned by providers."""

    # This is our placeholder value, shouldn't be encountered in a remote server response
    UNKNOWN_REASON = 0
    """An error code whose description is not present in this enum."""

    SERVER_ERROR = -32000
    """Reserved for implementation-defined server-errors. See the message for details."""

    INVALID_REQUEST = -32600
    """The JSON sent is not a valid Request object."""

    METHOD_NOT_FOUND = -32601
    """The method does not exist / is not available."""

    INVALID_PARAMETER = -32602
    """Invalid method parameter(s)."""

    EXECUTION_ERROR = 3
    """Contract transaction failed during execution. See the data for details."""

    @classmethod
    def from_int(cls, val: int) -> "RPCErrorCode":
        try:
            return cls(val)
        except ValueError:
            return cls.UNKNOWN_REASON


# Need a newtype because unlike all other integers, this one is not hexified on serialization.
ErrorCode = NewType("ErrorCode", int)


@dataclass
class RPCError(Exception):
    """A wrapper for a call execution error returned as a proper RPC response."""

    # Taking an integer and not `RPCErrorCode` here
    # since the codes may differ between providers.
    code: ErrorCode
    message: str
    data: None | bytes = None

    @classmethod
    def invalid_request(cls) -> "RPCError":
        return cls(ErrorCode(RPCErrorCode.INVALID_REQUEST.value), "invalid json request")


# EIP-2930 transaction
@dataclass
class Type2Transaction:
    # "type": 2
    chain_id: int
    value: Amount
    gas: int
    max_fee_per_gas: Amount
    max_priority_fee_per_gas: Amount
    nonce: int
    to: None | Address = None
    data: None | bytes = None


@dataclass
class EthCallParams:
    """Transaction fields for ``eth_call``."""

    to: Address
    from_: None | Address = None
    gas: None | int = None
    gas_price: int = 0
    value: Amount = Amount(0)
    data: None | bytes = None


@dataclass
class EstimateGasParams:
    """Transaction fields for ``eth_estimateGas``."""

    from_: Address
    to: None | Address = None
    gas: None | int = None
    gas_price: int = 0
    nonce: None | int = None
    value: Amount = Amount(0)
    data: None | bytes = None


@dataclass
class FilterParams:
    """Filter parameters for ``eth_getLogs`` or ``eth_newFilter``."""

    from_block: None | int | Block = None
    to_block: None | int | Block = None
    address: None | Address | tuple[Address, ...] = None
    topics: None | tuple[None | LogTopic | tuple[LogTopic, ...], ...] = None
