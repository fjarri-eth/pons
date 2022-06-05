from abc import ABC, abstractmethod
from functools import cached_property
import inspect
from itertools import chain
from typing import (
    Any,
    AbstractSet,
    Iterable,
    List,
    Dict,
    Optional,
    Union,
    Mapping,
    TypeVar,
    Generic,
    Iterator,
    Sequence,
    Tuple,
)

from . import abi
from ._abi_types import Type, dispatch_types, dispatch_type, encode_args, decode_args, keccak
from ._entities import LogTopic, LogEntry


class Signature:
    """
    Generalized signature of either inputs or outputs of a method.
    """

    def __init__(self, parameters: Union[Mapping[str, Type], Sequence[Type]]):
        if isinstance(parameters, Mapping):
            self._signature = inspect.Signature(
                parameters=[
                    inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                    for name, tp in parameters.items()
                ]
            )
            self._types = list(parameters.values())
            self._named_parameters = True
        else:
            self._signature = inspect.Signature(
                parameters=[
                    inspect.Parameter(f"_{i}", inspect.Parameter.POSITIONAL_ONLY)
                    for i in range(len(parameters))
                ]
            )
            self._types = list(parameters)
            self._named_parameters = False

    @cached_property
    def canonical_form(self) -> str:
        """
        Returns the signature serialized in the canonical form as a string.
        """
        return "(" + ",".join(tp.canonical_form for tp in self._types) + ")"

    def encode(self, *args, **kwargs) -> bytes:
        """
        Encodes assorted positional/keyword arguments into the bytestring
        according to the ABI format.
        """
        bound_args = self._signature.bind(*args, **kwargs)
        return encode_args(*zip(self._types, bound_args.args))

    def decode_into_tuple(self, value_bytes: bytes) -> Tuple[Any, ...]:
        """
        Decodes the packed bytestring into a list of values.
        """
        return decode_args(self._types, value_bytes)

    def decode_into_dict(self, value_bytes: bytes) -> Dict[str, Any]:
        """
        Decodes the packed bytestring into a dict of values.
        """
        decoded = self.decode_into_tuple(value_bytes)
        return {name: val for name, val in zip(self._signature.parameters, decoded)}

    def __str__(self):
        if self._named_parameters:
            params = ", ".join(
                f"{tp.canonical_form} {name}"
                for name, tp in zip(self._signature.parameters, self._types)
            )
        else:
            params = ", ".join(f"{tp.canonical_form}" for tp in self._types)
        return f"({params})"


class Either:
    """
    Denotes an `OR` operation when filtering events.
    """

    def __init__(self, *items: Any):
        self.items = items


class EventSignature:
    """
    A signature representing the constructor of an event (that is, its fields).
    """

    def __init__(self, parameters: Mapping[str, Type], indexed: AbstractSet[str]):
        self._signature = inspect.Signature(
            parameters=[
                inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                for name, tp in parameters.items()
                if name in indexed
            ]
        )
        self._types = parameters
        self._types_nonindexed = {
            name: self._types[name] for name in parameters if name not in indexed
        }
        self._indexed = indexed

    def encode_to_topics(self, *args, **kwargs) -> Tuple[Optional[Tuple[bytes, ...]], ...]:
        """
        Binds given arguments to event's indexed parameters
        and encodes them as log topics.
        """

        bound_args = self._signature.bind_partial(*args, **kwargs)

        encoded_topics: List[Optional[Tuple[bytes, ...]]] = []
        for param_name in self._signature.parameters:
            if param_name not in bound_args.arguments:
                encoded_topics.append(None)
                continue

            bound_val = bound_args.arguments[param_name]
            tp = self._types[param_name]

            if isinstance(bound_val, Either):
                encoded_val = tuple(tp.encode_to_topic(elem) for elem in bound_val.items)
            else:
                # Make it a one-element tuple to simplify type signatures.
                encoded_val = (tp.encode_to_topic(bound_val),)

            encoded_topics.append(encoded_val)

        # remove trailing `None`s - they are redundant
        while encoded_topics and encoded_topics[-1] is None:
            encoded_topics.pop()

        return tuple(encoded_topics)

    def decode_log_entry(self, topics: Sequence[bytes], data: bytes) -> Dict[str, Any]:
        """
        Decodes the event fields from the given log entry data.
        """
        if len(topics) != len(self._indexed):
            raise ValueError(
                f"The number of topics in the log entry ({len(topics)}) does not match "
                f"the number of indexed fields in the event ({len(self._indexed)})"
            )

        decoded_topics = {
            name: self._types[name].decode_from_topic(topic)
            for name, topic in zip(self._signature.parameters, topics)
        }

        decoded_data_tuple = decode_args(self._types_nonindexed.values(), data)
        decoded_data = dict(zip(self._types_nonindexed, decoded_data_tuple))

        result = {}
        for name in self._types:
            if name in decoded_topics:
                result[name] = decoded_topics[name]
            else:
                result[name] = decoded_data[name]

        return result

    @cached_property
    def canonical_form(self) -> str:
        """
        Returns the signature serialized in the canonical form as a string.
        """
        return "(" + ",".join(tp.canonical_form for tp in self._types.values()) + ")"

    @cached_property
    def canonical_form_nonindexed(self) -> str:
        """
        Returns the signature serialized in the canonical form as a string.
        """
        return "(" + ",".join(tp.canonical_form for tp in self._types_nonindexed.values()) + ")"

    def __str__(self):
        params = []
        for name, tp in self._types.items():
            indexed = "indexed " if name in self._indexed else ""
            params.append(f"{tp.canonical_form} {indexed}{name}")
        return "(" + ", ".join(params) + ")"


class Method(ABC):
    """
    An abstract type for a method (mutating or non-mutating).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Method name.
        """
        ...

    @property
    @abstractmethod
    def inputs(self) -> Signature:
        """
        Method's input signature.
        """
        ...

    @cached_property
    def selector(self) -> bytes:
        """
        Method's selector.
        """
        return keccak(self.name.encode() + self.inputs.canonical_form.encode())[:4]

    def _encode_call(self, *args, **kwargs) -> bytes:
        input_bytes = self.inputs.encode(*args, *kwargs)
        return self.selector + input_bytes


class Constructor:
    """
    Contract constructor.
    """

    inputs: Signature
    """Input signature."""

    payable: bool
    """Whether this method is marked as payable"""

    @classmethod
    def from_json(cls, method_entry: Dict[str, Any]) -> "Constructor":
        """
        Creates this object from a JSON ABI method entry.
        """
        if method_entry["type"] != "constructor":
            raise ValueError(
                "Constructor object must be created from a JSON entry with type='constructor'"
            )
        if "name" in method_entry:
            raise ValueError("Constructor's JSON entry cannot have a `name`")
        if "outputs" in method_entry and method_entry["outputs"]:
            raise ValueError("Constructor's JSON entry cannot have non-empty `outputs`")
        if method_entry["stateMutability"] not in ("nonpayable", "payable"):
            raise ValueError(
                "Constructor's JSON entry state mutability must be `nonpayable` or `payable`"
            )
        inputs = dispatch_types(method_entry.get("inputs", []))
        payable = method_entry["stateMutability"] == "payable"
        return cls(inputs, payable=payable)

    def __init__(self, inputs: Union[Mapping[str, Type], Sequence[Type]], payable: bool = False):
        self.inputs = Signature(inputs)
        self.payable = payable

    def __call__(self, *args, **kwargs) -> "ConstructorCall":
        """
        Returns an encoded call with given arguments.
        """
        input_bytes = self.inputs.encode(*args, *kwargs)
        return ConstructorCall(input_bytes)

    def __str__(self):
        return f"constructor{self.inputs} " + ("payable" if self.payable else "nonpayable")


class ReadMethod(Method):
    """
    A non-mutating contract method.
    """

    outputs: Signature
    """Method's output signature."""

    @classmethod
    def from_json(cls, method_entry: Dict[str, Any]) -> "ReadMethod":
        """
        Creates this object from a JSON ABI method entry.
        """
        if method_entry["type"] != "function":
            raise ValueError(
                "ReadMethod object must be created from a JSON entry with type='function'"
            )

        name = method_entry["name"]
        inputs = dispatch_types(method_entry["inputs"])
        if method_entry["stateMutability"] not in ("pure", "view"):
            raise ValueError(
                "Non-mutating method's JSON entry state mutability must be `pure` or `view`"
            )

        # Outputs can be anonymous
        outputs: Union[Dict[str, Type], List[Type]]
        if all(entry["name"] == "" for entry in method_entry["outputs"]):
            outputs = [dispatch_type(entry) for entry in method_entry["outputs"]]
        else:
            outputs = dispatch_types(method_entry["outputs"])

        return cls(name=name, inputs=inputs, outputs=outputs)

    def __init__(
        self,
        name: str,
        inputs: Union[Mapping[str, Type], Sequence[Type]],
        outputs: Union[Mapping[str, Type], Sequence[Type], Type],
    ):

        self._name = name
        self._inputs = Signature(inputs)

        if isinstance(outputs, Type):
            outputs = [outputs]
            self._single_output = True
        else:
            self._single_output = False

        self.outputs = Signature(outputs)

    @property
    def name(self) -> str:
        return self._name

    @property
    def inputs(self) -> Signature:
        return self._inputs

    def __call__(self, *args, **kwargs) -> "ReadCall":
        """
        Returns an encoded call with given arguments.
        """
        return ReadCall(self._encode_call(*args, **kwargs))

    def decode_output(self, output_bytes: bytes) -> Any:
        """
        Decodes the output from ABI-packed bytes.
        """
        results = self.outputs.decode_into_tuple(output_bytes)
        if self._single_output:
            results = results[0]
        return results

    def __str__(self):
        return f"function {self.name}{self.inputs} returns {self.outputs}"


class WriteMethod(Method):
    """
    A mutating contract method.
    """

    payable: bool
    """Whether this method is marked as payable"""

    @classmethod
    def from_json(cls, method_entry: Dict[str, Any]) -> "WriteMethod":
        """
        Creates this object from a JSON ABI method entry.
        """
        if method_entry["type"] != "function":
            raise ValueError(
                "WriteMethod object must be created from a JSON entry with type='function'"
            )

        name = method_entry["name"]
        inputs = dispatch_types(method_entry["inputs"])
        if "outputs" in method_entry and method_entry["outputs"]:
            raise ValueError("Mutating method's JSON entry cannot have non-empty `outputs`")
        if method_entry["stateMutability"] not in ("nonpayable", "payable"):
            raise ValueError(
                "Mutating method's JSON entry state mutability must be `nonpayable` or `payable`"
            )
        payable = method_entry["stateMutability"] == "payable"
        return cls(name=name, inputs=inputs, payable=payable)

    def __init__(
        self,
        name: str,
        inputs: Union[Mapping[str, Type], Sequence[Type]],
        payable: bool = False,
    ):

        self._name = name
        self._inputs = Signature(inputs)
        self.payable = payable

    @property
    def name(self) -> str:
        return self._name

    @property
    def inputs(self) -> Signature:
        return self._inputs

    def __call__(self, *args, **kwargs) -> "WriteCall":
        """
        Returns an encoded call with given arguments.
        """
        return WriteCall(self._encode_call(*args, **kwargs))

    def __str__(self):
        return f"function {self.name}{self.inputs} " + ("payable" if self.payable else "nonpayable")


class Event:
    """
    A contract event.
    """

    @classmethod
    def from_json(cls, event_entry: Dict[str, Any]) -> "Event":
        """
        Creates this object from a JSON ABI method entry.
        """
        if event_entry["type"] != "event":
            raise ValueError("Event object must be created from a JSON entry with type='event'")

        name = event_entry["name"]
        fields = dispatch_types(event_entry["inputs"])
        indexed = {input_["name"] for input_ in event_entry["inputs"] if input_["indexed"]}

        return cls(name=name, fields=fields, indexed=indexed, anonymous=event_entry["anonymous"])

    def __init__(
        self,
        name: str,
        fields: Mapping[str, Type],
        indexed: AbstractSet[str],
        anonymous: bool = False,
    ):
        if anonymous and len(indexed) > 4:
            raise ValueError("Anonymous events can have at most 4 indexed fields")
        elif not anonymous and len(indexed) > 3:
            raise ValueError("Non-anonymous events can have at most 3 indexed fields")

        self.name = name
        self.indexed = indexed
        self.fields = EventSignature(fields, indexed)
        self.anonymous = anonymous

    @cached_property
    def _topic(self) -> LogTopic:
        """
        The topic representing this event's signature.
        """
        return LogTopic(keccak(self.name.encode() + self.fields.canonical_form.encode()))

    def __call__(self, *args, **kwargs) -> "EventFilter":
        """
        Creates an event filter from provided values for indexed parameters.
        Some arguments can be omitted, which will mean that the filter
        will match events with any value of that parameter.
        :py:class:`Either` can be used to denote an OR operation and match
        either of several values of a parameter.
        """

        encoded_topics = self.fields.encode_to_topics(*args, **kwargs)

        log_topics: List[Optional[Tuple[LogTopic, ...]]] = []
        if not self.anonymous:
            log_topics.append((self._topic,))
        for topic in encoded_topics:
            if topic is None:
                log_topics.append(None)
            else:
                log_topics.append(tuple(LogTopic(elem) for elem in topic))

        return EventFilter(tuple(log_topics))

    def decode_log_entry(self, log_entry: LogEntry) -> Dict[str, Any]:
        """
        Decodes the event fields from the given log entry.
        Fields that cannot be decoded (indexed reference types,
        which are hashed before saving them to the log) are set to ``None``.
        """
        topics = log_entry.topics
        if not self.anonymous:
            if topics[0] != self._topic:
                raise ValueError("This log entry belongs to a different event")
            topics = topics[1:]

        return self.fields.decode_log_entry([bytes(topic) for topic in topics], log_entry.data)

    def __str__(self):
        return f"event {self.name}{self.fields}" + (" anonymous" if self.anonymous else "")


class EventFilter:
    """
    A filter for events coming from any contract address.
    """

    topics: Tuple[Optional[Tuple[LogTopic, ...]], ...]

    def __init__(self, topics: Tuple[Optional[Tuple[LogTopic, ...]], ...]):
        self.topics = topics


class Error:
    """
    A custom contract error.
    """

    @classmethod
    def from_json(cls, error_entry: Dict[str, Any]) -> "Error":
        """
        Creates this object from a JSON ABI method entry.
        """
        if error_entry["type"] != "error":
            raise ValueError("Error object must be created from a JSON entry with type='error'")

        name = error_entry["name"]
        fields = dispatch_types(error_entry["inputs"])

        return cls(name=name, fields=fields)

    def __init__(
        self,
        name: str,
        fields: Mapping[str, Type],
    ):
        self.name = name
        self.fields = Signature(fields)

    @cached_property
    def selector(self) -> bytes:
        """
        Error's selector.
        """
        return keccak(self.name.encode() + self.fields.canonical_form.encode())[:4]

    def decode_fields(self, data_bytes: bytes) -> Dict[str, Any]:
        """
        Decodes the error fields from the given packed data.
        """
        return self.fields.decode_into_dict(data_bytes)

    def __str__(self):
        return f"error {self.name}{self.fields}"


class Fallback:
    """
    A fallback method.
    """

    payable: bool
    """Whether this method is marked as payable"""

    @classmethod
    def from_json(cls, method_entry: Dict[str, Any]) -> "Fallback":
        """
        Creates this object from a JSON ABI method entry.
        """
        if method_entry["type"] != "fallback":
            raise ValueError(
                "Fallback object must be created from a JSON entry with type='fallback'"
            )
        if method_entry["stateMutability"] not in ("nonpayable", "payable"):
            raise ValueError(
                "Fallback method's JSON entry state mutability must be `nonpayable` or `payable`"
            )
        payable = method_entry["stateMutability"] == "payable"
        return cls(payable)

    def __init__(self, payable: bool = False):
        self.payable = payable

    def __str__(self):
        return "fallback() " + ("payable" if self.payable else "nonpayable")


class Receive:
    """
    A receive method.
    """

    payable: bool
    """Whether this method is marked as payable"""

    @classmethod
    def from_json(cls, method_entry: Dict[str, Any]) -> "Receive":
        """
        Creates this object from a JSON ABI method entry.
        """
        if method_entry["type"] != "receive":
            raise ValueError(
                "Receive object must be created from a JSON entry with type='fallback'"
            )
        if method_entry["stateMutability"] not in ("nonpayable", "payable"):
            raise ValueError(
                "Receive method's JSON entry state mutability must be `nonpayable` or `payable`"
            )
        payable = method_entry["stateMutability"] == "payable"
        return cls(payable)

    def __init__(self, payable: bool = False):
        self.payable = payable

    def __str__(self):
        return "receive() " + ("payable" if self.payable else "nonpayable")


class ConstructorCall:
    """
    A call to the contract's constructor.
    """

    input_bytes: bytes
    """Encoded call arguments."""

    def __init__(self, input_bytes: bytes):
        self.input_bytes = input_bytes


class ReadCall:
    """
    A call to a contract's non-mutating method.
    """

    data_bytes: bytes
    """Encoded call arguments with the selector."""

    def __init__(self, data_bytes: bytes):
        self.data_bytes = data_bytes


class WriteCall:
    """
    A call to a contract's mutating method.
    """

    data_bytes: bytes
    """Encoded call arguments with the selector."""

    def __init__(self, data_bytes: bytes):
        self.data_bytes = data_bytes


# This is force-documented as :py:class in ``api.rst``
# because Sphinx cannot resolve typevars correctly.
# See https://github.com/sphinx-doc/sphinx/issues/9705
MethodType = TypeVar("MethodType")


class Methods(Generic[MethodType]):
    """
    Bases: ``Generic`` [``MethodType``]

    A holder for named methods which can be accessed as attributes,
    or iterated over.
    """

    # :show-inheritance: is turned off in ``api.rst``, and we are documenting the base manually
    # (although without hyperlinking which I cannot get to work).
    # See https://github.com/sphinx-doc/sphinx/issues/9705

    def __init__(self, methods_dict: Mapping[str, MethodType]):
        self._methods_dict = methods_dict

    def __getattr__(self, method_name: str) -> MethodType:
        """
        Returns the method by name.
        """
        return self._methods_dict[method_name]

    def __iter__(self) -> Iterator[MethodType]:
        """
        Returns the iterator over all methods.
        """
        return iter(self._methods_dict.values())


PANIC_ERROR = Error("Panic", dict(code=abi.uint(256)))


LEGACY_ERROR = Error("Error", dict(message=abi.string))


class UnknownError(Exception):
    pass


class ContractABI:
    """
    A wrapper for contract ABI.

    Contract methods accessible as attributes of this object,
    with the type :py:class:`~pons._contract_abi.Method`.
    """

    constructor: Constructor
    """Contract's constructor."""

    fallback: Optional[Fallback]
    """Contract's fallback method."""

    receive: Optional[Receive]
    """Contract's receive method."""

    read: Methods[ReadMethod]
    """Contract's non-mutating methods."""

    write: Methods[WriteMethod]
    """Contract's mutating methods."""

    event: Methods[Event]
    """Contract's events."""

    error: Methods[Error]
    """Contract's errors."""

    @classmethod
    def from_json(cls, json_abi: list) -> "ContractABI":
        constructor = None
        fallback = None
        receive = None
        read = []
        write = []
        methods = set()
        events = {}
        errors = {}

        for entry in json_abi:

            if entry["type"] == "constructor":
                if constructor:
                    raise ValueError("JSON ABI contains more than one constructor declarations")
                constructor = Constructor.from_json(entry)

            elif entry["type"] == "function":
                if entry["name"] in methods:
                    # TODO: add support for overloaded methods
                    raise ValueError(
                        f"JSON ABI contains more than one declarations of `{entry['name']}`"
                    )

                methods.add(entry["name"])

                if entry["stateMutability"] in ("pure", "view"):
                    read.append(ReadMethod.from_json(entry))
                else:
                    write.append(WriteMethod.from_json(entry))

            elif entry["type"] == "fallback":
                if fallback:
                    raise ValueError("JSON ABI contains more than one fallback declarations")
                fallback = Fallback.from_json(entry)

            elif entry["type"] == "receive":
                if receive:
                    raise ValueError("JSON ABI contains more than one receive method declarations")
                receive = Receive.from_json(entry)

            elif entry["type"] == "event":
                if entry["name"] in events:
                    raise ValueError(
                        f"JSON ABI contains more than one declarations of `{entry['name']}`"
                    )
                events[entry["name"]] = Event.from_json(entry)

            elif entry["type"] == "error":
                if entry["name"] in errors:
                    raise ValueError(
                        f"JSON ABI contains more than one declarations of `{entry['name']}`"
                    )
                errors[entry["name"]] = Error.from_json(entry)

            else:
                raise ValueError(f"Unknown ABI entry type: {entry['type']}")

        return cls(
            constructor=constructor,
            fallback=fallback,
            receive=receive,
            read=read,
            write=write,
            events=events.values(),
            errors=errors.values(),
        )

    def __init__(
        self,
        constructor: Optional[Constructor] = None,
        fallback: Optional[Fallback] = None,
        receive: Optional[Receive] = None,
        read: Optional[Iterable[ReadMethod]] = None,
        write: Optional[Iterable[WriteMethod]] = None,
        events: Optional[Iterable[Event]] = None,
        errors: Optional[Iterable[Error]] = None,
    ):

        if constructor is None:
            constructor = Constructor(inputs=[])

        self.fallback = fallback
        self.receive = receive
        self.constructor = constructor
        self.read = Methods({method.name: method for method in (read or [])})
        self.write = Methods({method.name: method for method in (write or [])})
        self.event = Methods({event.name: event for event in (events or [])})
        self.error = Methods({error.name: error for error in (errors or [])})

        self._error_by_selector = {
            error.selector: error for error in chain([PANIC_ERROR, LEGACY_ERROR], self.error)
        }

    def resolve_error(self, error_data: bytes) -> Tuple[Error, Dict[str, Any]]:
        """
        Given the packed error data, attempts to find the error in the ABI
        and decode the data into its fields.
        """
        if len(error_data) < 4:
            raise ValueError("Error data too short to contain a selector")

        selector, data = error_data[:4], error_data[4:]

        if selector in self._error_by_selector:
            error = self._error_by_selector[selector]
            decoded = error.decode_fields(data)
            return error, decoded

        raise UnknownError(f"Could not find an error with selector {selector.hex()} in the ABI")

    def __str__(self):
        all_methods = (
            ([self.constructor] if self.constructor else [])
            + ([self.fallback] if self.fallback else [])
            + ([self.receive] if self.receive else [])
            + list(self.read)
            + list(self.write)
            + list(self.event)
            + list(self.error)
        )
        method_list = ["    " + str(method) for method in all_methods]
        return "{\n" + "\n".join(method_list) + "\n}"
