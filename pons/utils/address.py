from ethereum_rpc import Address, keccak


def get_create2_address(
    sender: Address, salt: bytes, init_code: bytes
) -> Address:
    if len(salt) != 32:
        raise TypeError(f"salt must be 32 bytes, {len(salt)} != 32")

    contract_address = keccak(
        b"\xff"
        + bytes.fromhex(sender.hex()[2:])
        + salt
        + keccak(init_code)
    ).hex()[-40:]
    return Address.from_hex(contract_address)