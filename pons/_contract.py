from typing import Any

from ._contract_abi import ContractABI, Methods, ReadMethod, WriteMethod
from ._entities import Address


class BoundConstructor:
    """
    A constructor bound to a specific contract's bytecode.
    """

    def __init__(self, compiled_contract: "CompiledContract"):
        self._bytecode = compiled_contract.bytecode
        self._contract_abi = compiled_contract.abi
        self._constructor = compiled_contract.abi.constructor

    def __call__(self, *args, **kwargs) -> "BoundConstructorCall":
        """
        Returns a constructor call with encoded arguments and bytecode.
        """
        call = self._constructor(*args, **kwargs)
        data_bytes = self._bytecode + call.input_bytes
        return BoundConstructorCall(self._contract_abi, data_bytes, self._constructor.payable)


class BoundConstructorCall:
    """
    A constructor call with encoded arguments and bytecode.
    """

    contract_abi: ContractABI
    """The corresponding contract's ABI"""

    payable: bool
    """Whether this call is payable."""

    data_bytes: bytes
    """Encoded arguments and the contract's bytecode."""

    def __init__(self, contract_abi: ContractABI, data_bytes: bytes, payable: bool):
        self.contract_abi = contract_abi
        self.payable = payable
        self.data_bytes = data_bytes


class BoundReadMethod:
    """
    A non-mutating method bound to a specific contract's address.
    """

    def __init__(self, contract_address: Address, method: ReadMethod):
        self._contract_address = contract_address
        self._method = method

    def __call__(self, *args, **kwargs) -> "BoundReadCall":
        """
        Returns a contract call with encoded arguments bound to a specific address.
        """
        call = self._method(*args, **kwargs)
        return BoundReadCall(self._method, self._contract_address, call.data_bytes)


class BoundReadCall:
    """
    A non-mutating method call with encoded arguments bound to a specific contract address.
    """

    contract_address: Address
    """The contract address."""

    data_bytes: bytes
    """Encoded call arguments with the selector."""

    def __init__(self, method: ReadMethod, contract_address: Address, data_bytes: bytes):
        self._method = method
        self.contract_address = contract_address
        self.data_bytes = data_bytes

    def decode_output(self, output_bytes: bytes) -> Any:
        """
        Decodes contract output packed into the bytestring.
        """
        return self._method.decode_output(output_bytes)


class BoundWriteMethod:
    """
    A mutating method bound to a specific contract's address.
    """

    def __init__(self, contract_address: Address, method: WriteMethod):
        self.contract_address = contract_address
        self.method = method

    def __call__(self, *args, **kwargs) -> "BoundWriteCall":
        """
        Returns a contract call with encoded arguments bound to a specific address.
        """
        call = self.method(*args, **kwargs)
        return BoundWriteCall(self.contract_address, call.data_bytes, self.method.payable)


class BoundWriteCall:
    """
    A mutating method call with encoded arguments bound to a specific contract address.
    """

    contract_address: Address
    """The contract address."""

    payable: bool
    """Whether this call is payable."""

    data_bytes: bytes
    """Encoded call arguments with the selector."""

    def __init__(self, contract_address: Address, data_bytes: bytes, payable: bool):
        self.payable = payable
        self.contract_address = contract_address
        self.data_bytes = data_bytes


class CompiledContract:
    """
    A compiled contract (ABI and bytecode).
    """

    abi: ContractABI
    """Contract's ABI."""

    bytecode: bytes
    """Contract's bytecode."""

    @classmethod
    def from_compiler_output(cls, json_abi: list, bytecode: bytes) -> "CompiledContract":
        """
        Creates a compiled contract object from the output of a Solidity compiler.
        """
        abi = ContractABI.from_json(json_abi)
        return cls(abi, bytecode)

    def __init__(self, abi: ContractABI, bytecode: bytes):
        self.abi = abi
        self.bytecode = bytecode

    @property
    def constructor(self) -> BoundConstructor:
        """
        Returns the constructor bound to this contract's bytecode.
        """
        return BoundConstructor(self)


class DeployedContract:
    """
    A deployed contract (ABI and address).
    """

    abi: ContractABI
    """Contract's ABI."""

    address: Address
    """Contract's address."""

    read: Methods[BoundReadMethod]
    """Contract's non-mutating methods bound to the address."""

    write: Methods[BoundWriteMethod]
    """Contract's mutating methods bound to the address."""

    def __init__(self, abi: ContractABI, address: Address):
        self.abi = abi
        self.address = address

        self.read = Methods(
            {method.name: BoundReadMethod(self.address, method) for method in self.abi.read}
        )
        self.write = Methods(
            {method.name: BoundWriteMethod(self.address, method) for method in self.abi.write}
        )
