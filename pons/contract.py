from pathlib import Path

from .contract_abi import ContractABI
from .types import Address


class CompiledContract:
    """
    A compiled contract (ABI and bytecode).
    """

    abi: ContractABI

    bytecode: bytes

    @classmethod
    def from_compiler_output(cls, json_abi: list, bytecode: bytes):
        abi = ContractABI.from_json(json_abi)
        return cls(abi, bytecode)

    def __init__(self, abi: ContractABI, bytecode: bytes):
        self.abi = abi
        self.bytecode = bytecode


class DeployedContract:
    """
    A deployed contract (ABI and address).
    """

    abi: ContractABI

    address: Address

    def __init__(self, abi: ContractABI, address: Address):
        self.abi = abi
        self.address = address
