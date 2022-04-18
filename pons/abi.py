from ._solidity_types import UInt, Int, Bytes, AddressType, String, Bool


def uint(bits):
    return UInt(bits)


def int(bits):
    return Int(bits)


def bytes(size):
    return Bytes(size)


address = AddressType()

string = String()

bool = Bool()
