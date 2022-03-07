from enum import Enum
from typing import NamedTuple, Union, Optional

from eth_utils import to_checksum_address, to_canonical_address, to_wei


class Wei:

    @classmethod
    def from_unit(cls, quantity: int, unit: str) -> 'Wei':
        return cls(to_wei(quantity, unit))

    def __init__(self, wei: int):
        self.wei = wei

    def __int__(self):
        return self.wei

    def __eq__(self, other):
        return type(self) == type(other) and self.wei == other.wei

    def __sub__(self, other):
        assert type(other) == type(self)
        return Wei(self.wei - other.wei)

    def __gt__(self, other):
        assert type(other) == type(self)
        return self.wei > other.wei

    def __str__(self):
        return f"{self.wei / 10**18} ETH"


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
        return isinstance(other, Address) and self._address_bytes == other._address_bytes


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


def encode_wei(val: Wei) -> str:
    return encode_quantity(int(val))


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


def decode_wei(val: str) -> Wei:
    return Wei(decode_quantity(val))


def decode_tx_hash(val: str) -> TxHash:
    return TxHash(decode_data(val))
