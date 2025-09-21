from abc import ABC, abstractmethod
from typing import Any

from ethereum_rpc import Address, LogEntry, LogTopic

from ._contract_abi import (
    ABI_JSON,
    ContractABI,
    Error,
    Event,
    EventFilter,
    Method,
    Methods,
    MultiMethod,
)


class BoundConstructor:
    """A constructor bound to a specific contract's bytecode."""

    def __init__(self, compiled_contract: "CompiledContract"):
        self._bytecode = compiled_contract.bytecode
        self._contract_abi = compiled_contract.abi
        self._constructor = compiled_contract.abi.constructor

    def __call__(self, *args: Any, **kwargs: Any) -> "BoundConstructorCall":
        """Returns a constructor call with encoded arguments and bytecode."""
        call = self._constructor(*args, **kwargs)
        data_bytes = self._bytecode + call.input_bytes
        return BoundConstructorCall(
            self._contract_abi, data_bytes, payable=self._constructor.payable
        )


class BoundConstructorCall:
    """A constructor call with encoded arguments and bytecode."""

    contract_abi: ContractABI
    """The corresponding contract's ABI"""

    payable: bool
    """Whether this call is payable."""

    data_bytes: bytes
    """Encoded arguments and the contract's bytecode."""

    def __init__(self, contract_abi: ContractABI, data_bytes: bytes, *, payable: bool):
        self.contract_abi = contract_abi
        self.payable = payable
        self.data_bytes = data_bytes


class BoundMethod:
    """A regular method bound to a specific contract's address."""

    def __init__(
        self,
        contract_abi: ContractABI,
        contract_address: Address,
        method: Method | MultiMethod,
    ):
        self._contract_abi = contract_abi
        self._contract_address = contract_address
        self._method = method

    def __call__(self, *args: Any, **kwargs: Any) -> "BoundMethodCall":
        """Returns a contract call with encoded arguments bound to a specific address."""
        call = self._method(*args, **kwargs)
        return BoundMethodCall(
            self._contract_abi, call.method, self._contract_address, call.data_bytes
        )


class BaseBoundMethodCall(ABC):
    """The base class for contract method calls bound to a specific contract address."""

    @property
    @abstractmethod
    def contract_abi(self) -> ContractABI:
        """The corresponding contract's ABI."""

    @property
    @abstractmethod
    def data_bytes(self) -> bytes:
        """Encoded call arguments with the selector."""

    @property
    @abstractmethod
    def payable(self) -> bool:
        """Whether this method is marked as ``payable``."""

    @property
    @abstractmethod
    def mutating(self) -> bool:
        """Whether this method is marked as ``payable`` or ``nonpayable``."""

    @property
    @abstractmethod
    def contract_address(self) -> Address:
        """The contract address."""

    @abstractmethod
    def decode_output(self, output_bytes: bytes) -> Any:
        """Decodes contract output packed into the bytestring."""


class BoundMethodCall(BaseBoundMethodCall):
    """A regular method call with encoded arguments bound to a specific contract address."""

    def __init__(
        self,
        contract_abi: ContractABI,
        method: Method,
        contract_address: Address,
        data_bytes: bytes,
    ):
        self._method = method
        self._contract_abi = contract_abi
        self._data_bytes = data_bytes
        self._contract_address = contract_address

    @property
    def contract_abi(self) -> ContractABI:
        return self._contract_abi

    @property
    def data_bytes(self) -> bytes:
        return self._data_bytes

    @property
    def payable(self) -> bool:
        return self._method.payable

    @property
    def mutating(self) -> bool:
        return self._method.mutating

    @property
    def contract_address(self) -> Address:
        return self._contract_address

    def decode_output(self, output_bytes: bytes) -> Any:
        return self._method.decode_output(output_bytes)


class BoundEvent:
    """An event creation call with encoded topics bound to a specific contract address."""

    def __init__(self, contract_address: Address, event: Event):
        self.contract_address = contract_address
        self.event = event

    def __call__(self, *args: Any, **kwargs: Any) -> "BoundEventFilter":
        """Returns an event filter with encoded arguments bound to a specific address."""
        return BoundEventFilter(self.contract_address, self.event, self.event(*args, **kwargs))


class BoundEventFilter:
    """An event filter bound to a specific contract address."""

    contract_address: Address
    """The contract address."""

    topics: tuple[None | tuple[LogTopic, ...], ...]
    """Encoded topics for filtering."""

    def __init__(self, contract_address: Address, event: Event, event_filter: EventFilter):
        self.contract_address = contract_address
        self.topics = event_filter.topics
        self._event = event

    def decode_log_entry(self, log_entry: LogEntry) -> dict[str, Any]:
        if log_entry.address != self.contract_address:
            raise ValueError("Log entry originates from a different contract")
        return self._event.decode_log_entry(log_entry)


class CompiledContract:
    """A compiled contract (ABI and bytecode)."""

    abi: ContractABI
    """Contract's ABI."""

    bytecode: bytes
    """Contract's bytecode."""

    @classmethod
    def from_compiler_output(
        cls, json_abi: list[dict[str, ABI_JSON]], bytecode: bytes
    ) -> "CompiledContract":
        """Creates a compiled contract object from the output of a Solidity compiler."""
        abi = ContractABI.from_json(json_abi)
        return cls(abi, bytecode)

    def __init__(self, abi: ContractABI, bytecode: bytes):
        self.abi = abi
        self.bytecode = bytecode

    @property
    def constructor(self) -> BoundConstructor:
        """Returns the constructor bound to this contract's bytecode."""
        return BoundConstructor(self)


class DeployedContract:
    """A deployed contract (ABI and address)."""

    abi: ContractABI
    """Contract's ABI."""

    address: Address
    """Contract's address."""

    method: Methods[BoundMethod]
    """Contract's regular methods bound to the address."""

    event: Methods[BoundEvent]
    """Contract's events bound to the address."""

    error: Methods[Error]
    """Contract's errors."""

    def __init__(self, abi: ContractABI, address: Address):
        self.abi = abi
        self.address = address

        self.method = Methods(
            {method.name: BoundMethod(self.abi, self.address, method) for method in self.abi.method}
        )
        self.event = Methods(
            {event.name: BoundEvent(self.address, event) for event in self.abi.event}
        )
        self.error = self.abi.error
