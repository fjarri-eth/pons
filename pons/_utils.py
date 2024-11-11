from ethereum_rpc import Address, keccak


def _rlp_encode(value: int | bytes | list[int | bytes]) -> bytes:
    """
    A limited subset of RLP encoding, so that we don't have to carry a whole `rlp` dependency
    just for contract address calculation.
    """
    list_size_limit = 55
    list_prefix = 0xC0
    string_size_limit = 55
    string_prefix = 0x80
    small_int_limit = 0x7F

    if isinstance(value, list):
        items = [_rlp_encode(item) for item in value]
        list_bytes = b"".join(items)
        assert len(list_bytes) <= list_size_limit  # noqa: S101
        return (list_prefix + len(list_bytes)).to_bytes(1, byteorder="big") + list_bytes

    if isinstance(value, int):
        # Note that there is an error in the official docs.
        # It says "For a single byte whose value is in the [0x00, 0x7f] (decimal [0, 127]) range,
        # that byte is its own RLP encoding."
        # But the encoding of `0` is `0x80`, not `0x00`
        # (that is, the encoding of a 0-length string).
        if 0 < value <= small_int_limit:
            return value.to_bytes(1, byteorder="big")
        value_len = (value.bit_length() + 7) // 8
        return _rlp_encode(value.to_bytes(value_len, byteorder="big"))

    assert len(value) <= string_size_limit  # noqa: S101
    return (string_prefix + len(value)).to_bytes(1, byteorder="big") + value


def get_create_address(deployer: Address, nonce: int) -> Address:
    """
    Returns the deterministic deployed contract address as produced by ``CREATE`` opcode.
    Here `deployer` is the contract address invoking ``CREATE`` (if initiated in a contract),
    or the transaction initiator, if a contract is created via an RPC transaction.
    ``init_code`` is the deployment code (see :py:attr:`~pons.BoundConstructorCall.data_bytes`).
    """
    # This will not hit the length limits since the nonce length is 32 bytes,
    # and the address length is 20 bytes, which, with length specifiers, is 54 bytes in total.
    contract_address = keccak(_rlp_encode([bytes(deployer), nonce]))[-20:]
    return Address(contract_address)


def get_create2_address(deployer: Address, init_code: bytes, salt: bytes) -> Address:
    """
    Returns the deterministic deployed contract address as produced by ``CREATE2`` opcode.
    Here `deployer` is the contract address invoking ``CREATE2``
    (**not** the transaction initiator),
    ``init_code`` is the deployment code (see :py:attr:`~pons.BoundConstructorCall.data_bytes`),
    and ``salt`` is a length 32 bytestring.
    """
    if len(salt) != 32:  # noqa: PLR2004
        raise ValueError("Salt must be 32 bytes in length")
    contract_address = keccak(b"\xff" + bytes(deployer) + salt + keccak(init_code))[-20:]
    return Address(contract_address)
