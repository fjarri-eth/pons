from enum import Enum
from typing import NamedTuple, Union, Optional, Tuple

from eth_utils import to_checksum_address, to_canonical_address


class Amount:
    """
    Represents a sum in the chain's native currency.

    Can be subclassed to represent specific currencies of different networks (ETH, MATIC etc).
    Arithmetic and comparison methods perform strict type checking,
    so different currency objects cannot be compared or added to each other.
    """

    @classmethod
    def wei(cls, value: int) -> 'Amount':
        """
        Creates a sum from the amount in wei (``10^(-18)`` of the main unit).
        """
        return cls(value)

    @classmethod
    def gwei(cls, value: Union[int, float]) -> 'Amount':
        """
        Creates a sum from the amount in gwei (``10^(-9)`` of the main unit).
        """
        return cls(int(10**9 * value))

    @classmethod
    def ether(cls, value: Union[int, float]) -> 'Amount':
        """
        Creates a sum from the amount in the main currency unit.
        """
        return cls(int(10**18 * value))

    def __init__(self, wei: int):
        if not isinstance(wei, int):
            raise TypeError(f"The amount must be an integer, got {repr(wei)}")
        if wei < 0:
            raise ValueError(f"The amount must be non-negative, got {wei}")
        self._wei = wei

    def as_wei(self) -> int:
        """
        Returns the amount in wei.
        """
        return self._wei

    def as_gwei(self) -> float:
        """
        Returns the amount in gwei.
        """
        return self._wei / 10**9

    def as_ether(self) -> float:
        """
        Returns the amount in the main currency unit.
        """
        return self._wei / 10**18

    def __eq__(self, other):
        if type(self) != type(other):
            raise TypeError(f"Incompatible types: {type(self)} and {type(other)}")
        return self._wei == other._wei

    def __sub__(self, other):
        if type(self) != type(other):
            raise TypeError(f"Incompatible types: {type(self)} and {type(other)}")
        return self.wei(self._wei - other._wei)

    def __mul__(self, other: int):
        if not isinstance(other, int):
            raise TypeError(f"Expected an integer, got {type(other)}")
        return self.wei(self._wei * other)

    def __gt__(self, other):
        if type(self) != type(other):
            raise TypeError(f"Incompatible types: {type(self)} and {type(other)}")
        return self._wei > other._wei

    def __ge__(self, other):
        if type(self) != type(other):
            raise TypeError(f"Incompatible types: {type(self)} and {type(other)}")
        return self._wei >= other._wei

    def __repr__(self):
        return f"Amount({self._wei})"


class Address:
    """
    Represents an Ethereum address.
    """

    @classmethod
    def from_hex(cls, address_str: str) -> 'Address':
        """
        Creates the address from a hex representation
        (with or without the ``0x`` prefix, checksummed or not).
        """
        return cls(to_canonical_address(address_str))

    def __init__(self, address_bytes: bytes):
        if not isinstance(address_bytes, bytes):
            raise TypeError(f"Address must be a bytestring, got {repr(address_bytes)}")
        if len(address_bytes) != 20:
            raise ValueError(f"Address must be 20 bytes long, got {repr(address_bytes)}")
        self._address_bytes = address_bytes

    def __bytes__(self):
        return self._address_bytes

    def as_checksum(self) -> str:
        """
        Retunrs the checksummed hex representation of the address.
        """
        return to_checksum_address(self._address_bytes)

    def __str__(self):
        return self.as_checksum()

    def __repr__(self):
        return f"Address.from_hex({self})"

    def __hash__(self):
        return hash(self._address_bytes)

    def __eq__(self, other):
        if type(self) != type(other):
            raise TypeError(f"Incompatible types: {type(self)} and {type(other)}")
        return self._address_bytes == other._address_bytes


class Block(Enum):
    """
    Block aliases supported by Ethereum RPC.
    """

    LATEST = 'latest'
    """The latest confirmed block"""

    EARLIEST = 'earliest'
    """The earliest block"""

    PENDING = 'pending'
    """Currently pending block"""


class TxHash:
    """
    A wrapper for the transaction hash.
    """

    def __init__(self, tx_hash: bytes):
        if not isinstance(tx_hash, bytes):
            raise TypeError(f"Transaction hash must be a bytestring, got {repr(tx_hash)}")
        if len(tx_hash) != 32:
            raise ValueError(f"Transaction hash must be 32 bytes long, got {repr(tx_hash)}")
        self._tx_hash = tx_hash

    def __bytes__(self):
        return self._tx_hash


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


def encode_quantity(val: int) -> str:
    return hex(val)


def encode_data(val: bytes) -> str:
    return '0x' + val.hex()


def encode_address(val: Address) -> str:
    return val.as_checksum()


def encode_amount(val: Amount) -> str:
    return encode_quantity(val.as_wei())


def encode_block(val: Union[int, Block]) -> str:
    if isinstance(val, Block):
        return val.value
    else:
        return encode_quantity(val)


def encode_tx_hash(val: TxHash) -> str:
    return encode_data(bytes(val))


def decode_quantity(val: str) -> int:
    if not val.startswith('0x'):
        raise ValueError("Encoded quantity must start with `0x`")
    return int(val, 16)


def decode_data(val: str) -> bytes:
    if not val.startswith('0x'):
        raise ValueError("Encoded data must start with `0x`")
    return bytes.fromhex(val[2:])


def decode_address(val: str) -> Address:
    return Address(decode_data(val))


def decode_amount(val: str) -> Amount:
    return Amount(decode_quantity(val))


def decode_tx_hash(val: str) -> TxHash:
    return TxHash(decode_data(val))
