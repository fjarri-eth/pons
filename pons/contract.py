from pathlib import Path

from .contract_abi import ContractABI, ConstructorCall, ReadCall, WriteCall, Methods
from .types import Address


class BoundConstructor:

    def __init__(self, compiled_contract: 'CompiledContract'):
        self.compiled_contract = compiled_contract
        self._bytecode = compiled_contract.bytecode
        self._constructor = compiled_contract.abi.constructor

    def __call__(self, *args, **kwargs):
        call = self._constructor(*args, **kwargs)
        return BoundConstructorCall(self.compiled_contract.abi, self._bytecode, call, self._constructor.payable)


class BoundConstructorCall:

    def __init__(self, contract_abi, bytecode: bytes, call: ConstructorCall, payable: bool):
        self.contract_abi = contract_abi
        self.payable = payable
        self.data_bytes = bytecode + call.input_bytes


class BoundReadMethod:

    def __init__(self, contract_address, method):
        self.contract_address = contract_address
        self.method = method

    def __call__(self, *args, **kwargs):
        call = self.method(*args, **kwargs)
        return BoundReadCall(self.method, self.contract_address, call.data_bytes)


class BoundReadCall:

    def __init__(self, method, contract_address, data_bytes):
        self._method = method
        self.contract_address = contract_address
        self.data_bytes = data_bytes

    def decode_output(self, output_bytes):
        return self._method.decode_output(output_bytes)


class BoundWriteMethod:

    def __init__(self, contract_address, method):
        self.contract_address = contract_address
        self.method = method

    def __call__(self, *args, **kwargs):
        call = self.method(*args, **kwargs)
        return BoundWriteCall(self.contract_address, call.data_bytes, self.method.payable)


class BoundWriteCall:

    def __init__(self, contract_address, data_bytes, payable):
        self.payable = payable
        self.contract_address = contract_address
        self.data_bytes = data_bytes


class CompiledContract:
    """
    A compiled contract (ABI and bytecode).
    """

    @classmethod
    def from_compiler_output(cls, json_abi: list, bytecode: bytes):
        abi = ContractABI.from_json(json_abi)
        return cls(abi, bytecode)

    def __init__(self, abi: ContractABI, bytecode: bytes):
        self.abi = abi
        self.bytecode = bytecode

    @property
    def constructor(self):
        return BoundConstructor(self)


class DeployedContract:
    """
    A deployed contract (ABI and address).
    """

    abi: ContractABI

    address: Address

    def __init__(self, abi: ContractABI, address: Address):
        self.abi = abi
        self.address = address

        self.read = Methods({method.name: BoundReadMethod(self.address, method) for method in self.abi.read})
        self.write = Methods({method.name: BoundWriteMethod(self.address, method) for method in self.abi.write})
