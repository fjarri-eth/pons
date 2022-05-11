from abc import ABC, abstractmethod
from functools import cached_property
from enum import Enum
from typing import NamedTuple, Union, Optional

from eth_utils import to_checksum_address, to_canonical_address

from ._provider import ResponseDict


class RPCDecodingError(Exception):
    """
    Raised on an error when decoding a value in an RPC response.
    """


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

    def encode(self) -> str:
        return encode_data(self._value)

    @classmethod
    def decode(cls, val: str):
        try:
            return cls(decode_data(val))
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

    def encode(self) -> str:
        return encode_quantity(self._value)

    @classmethod
    def decode(cls, val: str) -> "Amount":
        # `decode_quantity` will raise RPCDecodingError on any error,
        # and if it succeeds, constructor won't raise anything -
        # the value is already guaranteed to be `int` and non-negative
        return cls(decode_quantity(val))

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

    def encode(self) -> str:
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


class TxHash(TypedData):
    """
    A wrapper for the transaction hash.
    """

    def _length(self):
        return 32


class TxReceipt(NamedTuple):
    """
    Transaction receipt.
    """

    succeeded: bool
    """Whether the transaction was successful."""

    contract_address: Optional[Address]
    """
    If it was a successful deployment transaction,
    contains the address of the deployed contract.
    """

    gas_used: int
    """The amount of gas used by the transaction."""

    @classmethod
    def decode(cls, val: ResponseDict) -> "TxReceipt":
        contract_address = val["contractAddress"]
        return cls(
            succeeded=(decode_quantity(val["status"]) == 1),
            contract_address=Address.decode(contract_address) if contract_address else None,
            gas_used=decode_quantity(val["gasUsed"]),
        )


def encode_quantity(val: int) -> str:
    return hex(val)


def encode_data(val: bytes) -> str:
    return "0x" + val.hex()


def encode_block(val: Union[int, Block]) -> str:
    if isinstance(val, Block):
        return val.value
    else:
        return encode_quantity(val)


def decode_quantity(val: str) -> int:
    if not isinstance(val, str):
        raise RPCDecodingError("Encoded quantity must be a string")
    if not val.startswith("0x"):
        raise RPCDecodingError("Encoded quantity must start with `0x`")
    try:
        return int(val, 16)
    except ValueError as exc:
        raise RPCDecodingError(f"Could not convert encoded quantity to an integer: {exc}") from exc


def decode_data(val: str) -> bytes:
    if not isinstance(val, str):
        raise RPCDecodingError("Encoded data must be a string")
    if not val.startswith("0x"):
        raise RPCDecodingError("Encoded data must start with `0x`")
    try:
        return bytes.fromhex(val[2:])
    except ValueError as exc:
        raise RPCDecodingError(f"Could not convert encoded data to bytes: {exc}") from exc
