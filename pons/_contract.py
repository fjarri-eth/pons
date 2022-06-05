from typing import Any, Dict, Tuple, Optional

from ._contract_abi import ContractABI, Methods, ReadMethod, WriteMethod, Event, EventFilter, Error
from ._entities import Address, LogEntry, LogTopic


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

    def __init__(self, contract_abi: ContractABI, contract_address: Address, method: WriteMethod):
        self._contract_abi = contract_abi
        self._contract_address = contract_address
        self._method = method

    def __call__(self, *args, **kwargs) -> "BoundWriteCall":
        """
        Returns a contract call with encoded arguments bound to a specific address.
        """
        call = self._method(*args, **kwargs)
        return BoundWriteCall(
            self._contract_abi, self._contract_address, call.data_bytes, self._method.payable
        )


class BoundWriteCall:
    """
    A mutating method call with encoded arguments bound to a specific contract address.
    """

    contract_abi: ContractABI
    """The corresponding contract's ABI"""

    contract_address: Address
    """The contract address."""

    payable: bool
    """Whether this call is payable."""

    data_bytes: bytes
    """Encoded call arguments with the selector."""

    def __init__(
        self, contract_abi: ContractABI, contract_address: Address, data_bytes: bytes, payable: bool
    ):
        self.contract_abi = contract_abi
        self.payable = payable
        self.contract_address = contract_address
        self.data_bytes = data_bytes


class BoundEvent:
    """
    An event creation call with encoded topics bound to a specific contract address.
    """

    def __init__(self, contract_address: Address, event: Event):
        self.contract_address = contract_address
        self.event = event

    def __call__(self, *args, **kwargs) -> "BoundEventFilter":
        """
        Returns an event filter with encoded arguments bound to a specific address.
        """
        return BoundEventFilter(self.contract_address, self.event, self.event(*args, **kwargs))


class BoundEventFilter:
    """
    An event filter bound to a specific contract address.
    """

    contract_address: Address
    """The contract address."""

    topics: Tuple[Optional[Tuple[LogTopic, ...]], ...]
    """Encoded topics for filtering."""

    def __init__(self, contract_address: Address, event: Event, event_filter: EventFilter):
        self.contract_address = contract_address
        self.topics = event_filter.topics
        self._event = event

    def decode_log_entry(self, log_entry: LogEntry) -> Dict[str, Any]:
        if log_entry.address != self.contract_address:
            raise ValueError("Log entry originates from a different contract")
        return self._event.decode_log_entry(log_entry)


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

    event: Methods[BoundEvent]
    """Contract's events bound to the address."""

    error: Methods[Error]
    """Contract's errors."""

    def __init__(self, abi: ContractABI, address: Address):
        self.abi = abi
        self.address = address

        self.read = Methods(
            {method.name: BoundReadMethod(self.address, method) for method in self.abi.read}
        )
        self.write = Methods(
            {
                method.name: BoundWriteMethod(self.abi, self.address, method)
                for method in self.abi.write
            }
        )
        self.event = Methods(
            {event.name: BoundEvent(self.address, event) for event in self.abi.event}
        )
        self.error = self.abi.error
