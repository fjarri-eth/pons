from ethereum_rpc import Address, keccak


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
