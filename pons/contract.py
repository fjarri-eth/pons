from pathlib import Path

from .contract_abi import ContractABI
from .types import Address


class CompiledContract:

    def __init__(self, abi: ContractABI, bytecode: bytes):
        self.abi = abi
        self.bytecode = bytecode


class DeployedContract:

    def __init__(self, abi: ContractABI, address: Address):
        self.abi = abi
        self.address = address
