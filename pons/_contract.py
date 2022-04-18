from pathlib import Path

from ._contract_abi import (
    ContractABI, ConstructorCall, Constructor, ReadCall, WriteCall, Methods, ReadMethod, WriteMethod, Any)
from ._entities import Address


class BoundConstructor:

    def __init__(self, compiled_contract: 'CompiledContract'):
        self._bytecode = compiled_contract.bytecode
        self._contract_abi = compiled_contract.abi
        constructor = compiled_contract.abi.constructor
        if not constructor:
            # TODO: can we make an empty constructor for contracts without one?
            raise RuntimeError("This contract does not have a constructor")
        self._constructor = constructor

    def __call__(self, *args, **kwargs) -> 'BoundConstructorCall':
        call = self._constructor(*args, **kwargs)
        data_bytes = self._bytecode + call.input_bytes
        return BoundConstructorCall(self._contract_abi, data_bytes, self._constructor.payable)


class BoundConstructorCall:

    def __init__(self, contract_abi: ContractABI, data_bytes: bytes, payable: bool):
        self.contract_abi = contract_abi
        self.payable = payable
        self.data_bytes = data_bytes


class BoundReadMethod:

    def __init__(self, contract_address: Address, method: ReadMethod):
        self.contract_address = contract_address
        self.method = method

    def __call__(self, *args, **kwargs) -> 'BoundReadCall':
        call = self.method(*args, **kwargs)
        return BoundReadCall(self.method, self.contract_address, call.data_bytes)


class BoundReadCall:

    def __init__(self, method: ReadMethod, contract_address: Address, data_bytes: bytes):
        self._method = method
        self.contract_address = contract_address
        self.data_bytes = data_bytes

    def decode_output(self, output_bytes: bytes) -> Any:
        return self._method.decode_output(output_bytes)


class BoundWriteMethod:

    def __init__(self, contract_address: Address, method: WriteMethod):
        self.contract_address = contract_address
        self.method = method

    def __call__(self, *args, **kwargs) -> 'BoundWriteCall':
        call = self.method(*args, **kwargs)
        return BoundWriteCall(self.contract_address, call.data_bytes, self.method.payable)


class BoundWriteCall:

    def __init__(self, contract_address: Address, data_bytes: bytes, payable: bool):
        self.payable = payable
        self.contract_address = contract_address
        self.data_bytes = data_bytes


class CompiledContract:
    """
    A compiled contract (ABI and bytecode).
    """

    @classmethod
    def from_compiler_output(cls, json_abi: list, bytecode: bytes) -> 'CompiledContract':
        abi = ContractABI.from_json(json_abi)
        return cls(abi, bytecode)

    def __init__(self, abi: ContractABI, bytecode: bytes):
        self.abi = abi
        self.bytecode = bytecode

    @property
    def constructor(self) -> BoundConstructor:
        return BoundConstructor(self)


class DeployedContract:
    """
    A deployed contract (ABI and address).
    """

    abi: ContractABI

    address: Address

    read: Methods[BoundReadMethod]

    write: Methods[BoundWriteMethod]

    def __init__(self, abi: ContractABI, address: Address):
        self.abi = abi
        self.address = address

        self.read = Methods({method.name: BoundReadMethod(self.address, method) for method in self.abi.read})
        self.write = Methods({method.name: BoundWriteMethod(self.address, method) for method in self.abi.write})
