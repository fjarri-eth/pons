from enum import Enum
from typing import NamedTuple, Union, Optional, Tuple

from eth_utils import to_checksum_address, to_canonical_address


class Amount:

    @classmethod
    def wei(cls, value: int):
        return cls(value)

    @classmethod
    def gwei(cls, value: int):
        return cls(10**9 * value)

    @classmethod
    def ether(cls, value: int):
        return cls(10**18 * value)

    def __init__(self, wei: int):
        assert isinstance(wei, int)
        self._wei = wei

    def as_wei(self):
        return self._wei

    def as_gwei(self):
        return self._wei / 10**9

    def as_ether(self):
        return self._wei / 10**18

    def __eq__(self, other):
        assert type(other) == type(self)
        return self._wei == other._wei

    def __sub__(self, other):
        assert type(other) == type(self)
        return self.wei(self._wei - other._wei)

    def __mul__(self, other: int):
        assert isinstance(other, int)
        return self.wei(self._wei * other)

    def __gt__(self, other):
        assert type(other) == type(self)
        return self._wei > other._wei

    def __ge__(self, other):
        assert type(other) == type(self)
        return self._wei >= other._wei

    def __repr__(self):
        return f"Amount({self._wei})"


class Address:

    @classmethod
    def from_hex(cls, address_str: str) -> 'Address':
        return cls(to_canonical_address(address_str))

    def __init__(self, address_bytes: bytes):
        assert len(address_bytes) == 20
        self._address_bytes = address_bytes

    def __bytes__(self):
        return self._address_bytes

    def as_checksum(self) -> str:
        return to_checksum_address(self._address_bytes)

    def __str__(self):
        return self.as_checksum()

    def __repr__(self):
        return f"Address.from_hex({self})"

    def __hash__(self):
        return hash(self._address_bytes)

    def __eq__(self, other):
        assert isinstance(other, Address)
        return self._address_bytes == other._address_bytes


class Block(Enum):
    LATEST = 'latest'
    EARLIEST = 'earliest'
    PENDING = 'pending'


class TxHash:

    def __init__(self, tx_hash: bytes):
        assert len(tx_hash) == 32
        self._tx_hash = tx_hash

    def __bytes__(self):
        return self._tx_hash


class TxReceipt(NamedTuple):
    succeeded: bool
    contract_address: Optional[Address]
    gas_used: int


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
    assert isinstance(val, str) and val.startswith('0x')
    return int(val, 16)


def decode_data(val: str) -> bytes:
    assert isinstance(val, str) and val.startswith('0x')
    return bytes.fromhex(val[2:])


def decode_address(val: str) -> Address:
    return Address(decode_data(val))


def decode_amount(val: str) -> Amount:
    return Amount(decode_quantity(val))


def decode_tx_hash(val: str) -> TxHash:
    return TxHash(decode_data(val))
