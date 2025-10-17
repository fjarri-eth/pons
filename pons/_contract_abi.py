import inspect
from collections.abc import Iterable, Iterator, Mapping, Sequence
from collections.abc import Set as AbstractSet
from enum import Enum
from functools import cached_property
from inspect import BoundArguments
from itertools import chain
from keyword import iskeyword
from typing import Any, Generic, TypeVar, cast

from ethereum_rpc import LogEntry, LogTopic, keccak

from . import abi
from ._abi_types import ABI_JSON, Type, decode_args, dispatch_type, dispatch_types, encode_args

# Anonymous events can have at most 4 indexed fields
ANONYMOUS_EVENT_INDEXED_FIELDS = 4

# Anonymous events can have at most 4 indexed fields
EVENT_INDEXED_FIELDS = 3

# The number of bytes in a function selector.
SELECTOR_LENGTH = 4


# We are using the `inspect` machinery to bind arguments to parameters.
# From Py3.11 on it does not allow parameter names to coincide with keywords,
# so we have to escape them.
# This can be avoided if we write our own `inspect.Signature` implementation.
def make_name_safe(name: str) -> str:
    if iskeyword(name):
        return name + "_"
    return name


class Signature:
    """Generalized signature of either inputs or outputs of a method."""

    def __init__(self, parameters: Mapping[str, Type] | Sequence[Type]):
        if isinstance(parameters, Mapping):
            self._signature = inspect.Signature(
                parameters=[
                    inspect.Parameter(make_name_safe(name), inspect.Parameter.POSITIONAL_OR_KEYWORD)
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

    @property
    def empty(self) -> bool:
        return not bool(self._types)

    @cached_property
    def canonical_form(self) -> str:
        """Returns the signature serialized in the canonical form as a string."""
        return "(" + ",".join(tp.canonical_form for tp in self._types) + ")"

    def bind(self, *args: Any, **kwargs: Any) -> BoundArguments:
        return self._signature.bind(*args, **kwargs)

    def encode_bound(self, bound_args: BoundArguments) -> bytes:
        return encode_args(*zip(self._types, bound_args.args, strict=True))

    def encode(self, *args: Any, **kwargs: Any) -> bytes:
        """
        Encodes assorted positional/keyword arguments into the bytestring
        according to the ABI format.
        """
        bound_args = self.bind(*args, **kwargs)
        return self.encode_bound(bound_args)

    def decode_into_tuple(self, value_bytes: bytes) -> tuple[Any, ...]:
        """Decodes the packed bytestring into a list of values."""
        return decode_args(self._types, value_bytes)

    def decode_into_dict(self, value_bytes: bytes) -> dict[str, Any]:
        """Decodes the packed bytestring into a dict of values."""
        decoded = self.decode_into_tuple(value_bytes)
        return dict(zip(self._signature.parameters, decoded, strict=True))

    def __str__(self) -> str:
        if self._named_parameters:
            params = ", ".join(
                f"{tp.canonical_form} {name}"
                for name, tp in zip(self._signature.parameters, self._types, strict=True)
            )
        else:
            params = ", ".join(f"{tp.canonical_form}" for tp in self._types)
        return f"({params})"


class Either:
    """Denotes an `OR` operation when filtering events."""

    def __init__(self, *items: Any):
        self.items = items


class EventSignature:
    """A signature representing the constructor of an event (that is, its fields)."""

    def __init__(self, parameters: Mapping[str, Type], indexed: AbstractSet[str]):
        parameters = {make_name_safe(name): val for name, val in parameters.items()}
        indexed = {make_name_safe(name) for name in indexed}
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

    def encode_to_topics(self, *args: Any, **kwargs: Any) -> tuple[None | tuple[bytes, ...], ...]:
        """
        Binds given arguments to event's indexed parameters
        and encodes them as log topics.
        """
        bound_args = self._signature.bind_partial(*args, **kwargs)

        encoded_topics: list[None | tuple[bytes, ...]] = []
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

    def decode_log_entry(self, topics: Sequence[bytes], data: bytes) -> dict[str, Any]:
        """Decodes the event fields from the given log entry data."""
        if len(topics) != len(self._indexed):
            raise ValueError(
                f"The number of topics in the log entry ({len(topics)}) does not match "
                f"the number of indexed fields in the event ({len(self._indexed)})"
            )

        decoded_topics = {
            name: self._types[name].decode_from_topic(topic)
            for name, topic in zip(self._signature.parameters, topics, strict=True)
        }

        decoded_data_tuple = decode_args(self._types_nonindexed.values(), data)
        decoded_data = dict(zip(self._types_nonindexed, decoded_data_tuple, strict=True))

        result = {}
        for name in self._types:
            if name in decoded_topics:
                result[name] = decoded_topics[name]
            else:
                result[name] = decoded_data[name]

        return result

    @cached_property
    def canonical_form(self) -> str:
        """Returns the signature serialized in the canonical form as a string."""
        return "(" + ",".join(tp.canonical_form for tp in self._types.values()) + ")"

    @cached_property
    def canonical_form_nonindexed(self) -> str:
        """Returns the signature serialized in the canonical form as a string."""
        return "(" + ",".join(tp.canonical_form for tp in self._types_nonindexed.values()) + ")"

    def __str__(self) -> str:
        params = []
        for name, tp in self._types.items():
            indexed = "indexed " if name in self._indexed else ""
            params.append(f"{tp.canonical_form} {indexed}{name}")
        return "(" + ", ".join(params) + ")"


class Constructor:
    """
    Contract constructor.

    .. note::

       If the name of a parameter given to the constructor matches a Python keyword,
       ``_`` will be appended to it.
    """

    inputs: Signature
    """Input signature."""

    payable: bool
    """Whether this method is marked as payable"""

    @classmethod
    def from_json(cls, method_entry: ABI_JSON) -> "Constructor":
        # TODO (#83): use proper validation
        method_entry_typed = cast("Mapping[str, ABI_JSON]", method_entry)

        """Creates this object from a JSON ABI method entry."""
        if method_entry_typed["type"] != "constructor":
            raise ValueError(
                "Constructor object must be created from a JSON entry with type='constructor'"
            )
        if "name" in method_entry_typed:
            raise ValueError("Constructor's JSON entry cannot have a `name`")
        if method_entry_typed.get("outputs"):
            raise ValueError("Constructor's JSON entry cannot have non-empty `outputs`")
        if method_entry_typed["stateMutability"] not in ("nonpayable", "payable"):
            raise ValueError(
                "Constructor's JSON entry state mutability must be `nonpayable` or `payable`"
            )
        inputs = dispatch_types(method_entry_typed.get("inputs", []))
        payable = method_entry_typed["stateMutability"] == "payable"
        return cls(inputs, payable=payable)

    def __init__(self, inputs: Mapping[str, Type] | Sequence[Type], *, payable: bool = False):
        self.inputs = Signature(inputs)
        self.payable = payable

    def __call__(self, *args: Any, **kwargs: Any) -> "ConstructorCall":
        """Returns an encoded call with given arguments."""
        input_bytes = self.inputs.encode(*args, **kwargs)
        return ConstructorCall(input_bytes)

    def __str__(self) -> str:
        return f"constructor{self.inputs} " + ("payable" if self.payable else "nonpayable")


class Mutability(Enum):
    """Possible states of a contract's method mutability."""

    PURE = "pure"
    """Solidity's ``pure`` (does not read or write the contract state)."""
    VIEW = "view"
    """Solidity's ``view`` (may read the contract state)."""
    NONPAYABLE = "nonpayable"
    """Solidity's ``nonpayable`` (may write the contract state)."""
    PAYABLE = "payable"
    """
    Solidity's ``payable`` (may write the contract state
    and accept associated funds with transactions).
    """

    @classmethod
    def from_json(cls, entry: ABI_JSON) -> "Mutability":
        # TODO (#83): use proper validation
        entry_typed = cast("str", entry)

        values = dict(
            pure=Mutability.PURE,
            view=Mutability.VIEW,
            nonpayable=Mutability.NONPAYABLE,
            payable=Mutability.PAYABLE,
        )
        if entry_typed not in values:
            raise ValueError(f"Unknown mutability identifier: {entry}")
        return values[entry_typed]

    @property
    def payable(self) -> bool:
        return self == Mutability.PAYABLE

    @property
    def mutating(self) -> bool:
        return self in {Mutability.PAYABLE, Mutability.NONPAYABLE}


class Method:
    """
    A contract method.

    .. note::

       If the name of a parameter (input or output) given to the constructor
       matches a Python keyword, ``_`` will be appended to it.
    """

    name: str
    """The name of this method."""

    inputs: Signature
    """The input signature of this method."""

    outputs: Signature
    """Method's output signature."""

    payable: bool
    """Whether this method is marked as payable."""

    mutating: bool
    """Whether this method may mutate the contract state."""

    @classmethod
    def from_json(cls, method_entry: ABI_JSON) -> "Method":
        """Creates this object from a JSON ABI method entry."""
        # TODO (#83): use proper validation
        method_entry_typed = cast("Mapping[str, Any]", method_entry)

        if method_entry_typed["type"] != "function":
            raise ValueError("Method object must be created from a JSON entry with type='function'")

        name = method_entry_typed["name"]
        inputs = dispatch_types(method_entry_typed["inputs"])

        mutability = Mutability.from_json(method_entry_typed["stateMutability"])

        # Outputs can be anonymous
        outputs: dict[str, Type] | list[Type]
        if "outputs" not in method_entry_typed:
            outputs = []
        elif all(entry["name"] == "" for entry in method_entry_typed["outputs"]):
            outputs = [dispatch_type(entry) for entry in method_entry_typed["outputs"]]
        else:
            outputs = dispatch_types(method_entry_typed["outputs"])

        return cls(name=name, inputs=inputs, outputs=outputs, mutability=mutability)

    def __init__(
        self,
        name: str,
        mutability: Mutability,
        inputs: Mapping[str, Type] | Sequence[Type],
        outputs: None | Mapping[str, Type] | Sequence[Type] | Type = None,
    ):
        self.name = name
        self.inputs = Signature(inputs)
        self._mutability = mutability
        self.payable = mutability.payable
        self.mutating = mutability.mutating

        if outputs is None:
            outputs = []

        if isinstance(outputs, Type):
            outputs = [outputs]
            self._single_output = True
        else:
            self._single_output = False

        self.outputs = Signature(outputs)

    def bind(self, *args: Any, **kwargs: Any) -> BoundArguments:
        return self.inputs.bind(*args, **kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> "MethodCall":
        """Returns an encoded call with given arguments."""
        bound_args = self.bind(*args, **kwargs)
        return self.call_bound(bound_args)

    def call_bound(self, bound_args: BoundArguments) -> "MethodCall":
        input_bytes = self.inputs.encode_bound(bound_args)
        encoded = self.selector + input_bytes
        return MethodCall(self, encoded)

    @cached_property
    def selector(self) -> bytes:
        """Method's selector."""
        return keccak(self.name.encode() + self.inputs.canonical_form.encode())[:SELECTOR_LENGTH]

    def decode_output(self, output_bytes: bytes) -> Any:
        """Decodes the output from ABI-packed bytes."""
        results = self.outputs.decode_into_tuple(output_bytes)
        if self._single_output:
            results = results[0]
        return results

    def with_method(self, method: "Method") -> "MultiMethod":
        return MultiMethod(self, method)

    def __str__(self) -> str:
        returns = "" if self.outputs.empty else f" returns {self.outputs}"
        return f"function {self.name}{self.inputs} {self._mutability.value}{returns}"


class MultiMethod:
    """
    An overloaded contract method, containing several :py:class:`Method` objects with the same name
    but different input signatures.
    """

    def __init__(self, *methods: Method):
        if len(methods) == 0:
            raise ValueError("`methods` cannot be empty")
        first_method = methods[0]
        self._methods = {first_method.inputs.canonical_form: first_method}
        self._name = first_method.name

        for method in methods[1:]:
            self._add_method(method)

    def __getitem__(self, args: str) -> Method:
        """
        Returns the :py:class:`Method` with the given canonical form of an input signature
        (corresponding to :py:attr:`Signature.canonical_form`).
        """
        return self._methods[args]

    @property
    def name(self) -> str:
        """The name of this method."""
        return self._name

    @property
    def methods(self) -> dict[str, Method]:
        """All the overloaded methods, indexed by the canonical form of their input signatures."""
        return self._methods

    def _add_method(self, method: Method) -> None:
        if method.name != self.name:
            raise ValueError("All overloaded methods must have the same name")
        if method.inputs.canonical_form in self._methods:
            raise ValueError(
                f"A method {self.name}{method.inputs.canonical_form} "
                "is already registered in this MultiMethod"
            )
        self._methods[method.inputs.canonical_form] = method

    def with_method(self, method: Method) -> "MultiMethod":
        """Returns a new ``MultiMethod`` with the given method included."""
        new_mm = MultiMethod(*self._methods.values())
        new_mm._add_method(method)
        return new_mm

    def __call__(self, *args: Any, **kwds: Any) -> "MethodCall":
        """Returns an encoded call with given arguments."""
        for method in self._methods.values():
            try:
                bound_args = method.bind(*args, **kwds)
            except TypeError:
                # If it's a non-overloaded method, we do not want to complicate things
                if len(self._methods) == 1:
                    raise

                continue

            return method.call_bound(bound_args)

        raise TypeError("Could not find a suitable overloaded method for the given arguments")

    def __str__(self) -> str:
        return "; ".join(str(method) for method in self._methods.values())


class Event:
    """
    A contract event.

    .. note::

       If the name of a field given to the constructor matches a Python keyword,
       ``_`` will be appended to it.
    """

    @classmethod
    def from_json(cls, event_entry: ABI_JSON) -> "Event":
        """Creates this object from a JSON ABI method entry."""
        # TODO (#83): use proper validation
        event_entry_typed = cast("Mapping[str, Any]", event_entry)

        if event_entry_typed["type"] != "event":
            raise ValueError("Event object must be created from a JSON entry with type='event'")

        name = event_entry_typed["name"]
        fields = dispatch_types(event_entry_typed["inputs"])
        if isinstance(fields, list):
            raise TypeError("Event fields must be named")

        indexed = {input_["name"] for input_ in event_entry_typed["inputs"] if input_["indexed"]}

        return cls(
            name=name, fields=fields, indexed=indexed, anonymous=event_entry_typed["anonymous"]
        )

    def __init__(
        self,
        name: str,
        fields: Mapping[str, Type],
        indexed: AbstractSet[str],
        *,
        anonymous: bool = False,
    ):
        if anonymous and len(indexed) > ANONYMOUS_EVENT_INDEXED_FIELDS:
            raise ValueError(
                f"Anonymous events can have at most {ANONYMOUS_EVENT_INDEXED_FIELDS} indexed fields"
            )
        if not anonymous and len(indexed) > EVENT_INDEXED_FIELDS:
            raise ValueError(
                f"Non-anonymous events can have at most {EVENT_INDEXED_FIELDS} indexed fields"
            )

        self.name = name
        self.indexed = indexed
        self.fields = EventSignature(fields, indexed)
        self.anonymous = anonymous

    @cached_property
    def _topic(self) -> LogTopic:
        """The topic representing this event's signature."""
        return LogTopic(keccak(self.name.encode() + self.fields.canonical_form.encode()))

    def __call__(self, *args: Any, **kwargs: Any) -> "EventFilter":
        """
        Creates an event filter from provided values for indexed parameters.
        Some arguments can be omitted, which will mean that the filter
        will match events with any value of that parameter.
        :py:class:`Either` can be used to denote an OR operation and match
        either of several values of a parameter.
        """
        encoded_topics = self.fields.encode_to_topics(*args, **kwargs)

        log_topics: list[None | tuple[LogTopic, ...]] = []
        if not self.anonymous:
            log_topics.append((self._topic,))
        for topic in encoded_topics:
            if topic is None:
                log_topics.append(None)
            else:
                log_topics.append(tuple(LogTopic(elem) for elem in topic))

        return EventFilter(tuple(log_topics))

    def decode_log_entry(self, log_entry: LogEntry) -> dict[str, Any]:
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

    def __str__(self) -> str:
        return f"event {self.name}{self.fields}" + (" anonymous" if self.anonymous else "")


class EventFilter:
    """A filter for events coming from any contract address."""

    topics: tuple[None | tuple[LogTopic, ...], ...]

    def __init__(self, topics: tuple[None | tuple[LogTopic, ...], ...]):
        self.topics = topics


class Error:
    """A custom contract error."""

    @classmethod
    def from_json(cls, error_entry: ABI_JSON) -> "Error":
        """Creates this object from a JSON ABI method entry."""
        # TODO (#83): use proper validation
        error_entry_typed = cast("Mapping[str, Any]", error_entry)

        if error_entry_typed["type"] != "error":
            raise ValueError("Error object must be created from a JSON entry with type='error'")

        name = error_entry_typed["name"]
        fields = dispatch_types(error_entry_typed["inputs"])
        if isinstance(fields, list):
            raise TypeError("Error fields must be named")

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
        """Error's selector."""
        return keccak(self.name.encode() + self.fields.canonical_form.encode())[:SELECTOR_LENGTH]

    def decode_fields(self, data_bytes: bytes) -> dict[str, Any]:
        """Decodes the error fields from the given packed data."""
        return self.fields.decode_into_dict(data_bytes)

    def __str__(self) -> str:
        return f"error {self.name}{self.fields}"


class Fallback:
    """A fallback method."""

    payable: bool
    """Whether this method is marked as payable"""

    @classmethod
    def from_json(cls, method_entry: ABI_JSON) -> "Fallback":
        """Creates this object from a JSON ABI method entry."""
        # TODO (#83): use proper validation
        method_entry_typed = cast("Mapping[str, ABI_JSON]", method_entry)

        if method_entry_typed["type"] != "fallback":
            raise ValueError(
                "Fallback object must be created from a JSON entry with type='fallback'"
            )
        if method_entry_typed["stateMutability"] not in ("nonpayable", "payable"):
            raise ValueError(
                "Fallback method's JSON entry state mutability must be `nonpayable` or `payable`"
            )
        payable = method_entry_typed["stateMutability"] == "payable"
        return cls(payable=payable)

    def __init__(self, *, payable: bool = False):
        self.payable = payable

    def __str__(self) -> str:
        return "fallback() " + ("payable" if self.payable else "nonpayable")


class Receive:
    """A receive method."""

    payable: bool
    """Whether this method is marked as payable"""

    @classmethod
    def from_json(cls, method_entry: ABI_JSON) -> "Receive":
        """Creates this object from a JSON ABI method entry."""
        # TODO (#83): use proper validation
        method_entry_typed = cast("Mapping[str, ABI_JSON]", method_entry)

        if method_entry_typed["type"] != "receive":
            raise ValueError(
                "Receive object must be created from a JSON entry with type='fallback'"
            )
        if method_entry_typed["stateMutability"] not in ("nonpayable", "payable"):
            raise ValueError(
                "Receive method's JSON entry state mutability must be `nonpayable` or `payable`"
            )
        payable = method_entry_typed["stateMutability"] == "payable"
        return cls(payable=payable)

    def __init__(self, *, payable: bool = False):
        self.payable = payable

    def __str__(self) -> str:
        return "receive() " + ("payable" if self.payable else "nonpayable")


class ConstructorCall:
    """A call to the contract's constructor."""

    input_bytes: bytes
    """Encoded call arguments."""

    def __init__(self, input_bytes: bytes):
        self.input_bytes = input_bytes


class MethodCall:
    """A call to a contract's regular method."""

    data_bytes: bytes
    """Encoded call arguments with the selector."""

    method: Method
    """The method object that encoded this call."""

    def __init__(self, method: Method, data_bytes: bytes):
        self.method = method
        self.data_bytes = data_bytes


# This is force-documented as :py:class in ``api.rst``
# because Sphinx cannot resolve typevars correctly.
# See https://github.com/sphinx-doc/sphinx/issues/9705
MethodType = TypeVar("MethodType")


class Methods(Generic[MethodType]):
    """
    Bases: ``Generic`` [``MethodType``].

    A holder for named methods which can be accessed as attributes,
    or iterated over.
    """

    # :show-inheritance: is turned off in ``api.rst``, and we are documenting the base manually
    # (although without hyperlinking which I cannot get to work).
    # See https://github.com/sphinx-doc/sphinx/issues/9705

    def __init__(self, methods_dict: Mapping[str, MethodType]):
        self._methods_dict = methods_dict

    def __getattr__(self, method_name: str) -> MethodType:
        """Returns the method by name."""
        return self._methods_dict[method_name]

    def __iter__(self) -> Iterator[MethodType]:
        """Returns the iterator over all methods."""
        return iter(self._methods_dict.values())


PANIC_ERROR = Error("Panic", dict(code=abi.uint(256)))


LEGACY_ERROR = Error("Error", dict(message=abi.string))


class UnknownError(Exception):
    pass


class ContractABI:
    """
    A wrapper for contract ABI.

    Contract methods are grouped by type and are accessible via the attributes below.
    """

    constructor: Constructor
    """Contract's constructor."""

    fallback: None | Fallback
    """Contract's fallback method."""

    receive: None | Receive
    """Contract's receive method."""

    method: Methods[Method | MultiMethod]
    """Contract's regular methods."""

    event: Methods[Event]
    """Contract's events."""

    error: Methods[Error]
    """Contract's errors."""

    @classmethod
    def from_json(cls, json_abi: ABI_JSON) -> "ContractABI":  # noqa: C901, PLR0912
        """Creates this object from a JSON ABI (e.g. generated by a Solidity compiler)."""
        # TODO (#83): use proper validation
        json_abi_typed = cast("Sequence[Mapping[str, ABI_JSON]]", json_abi)

        constructor = None
        fallback = None
        receive = None
        methods: dict[Any, Method | MultiMethod] = {}
        events = {}
        errors = {}

        for entry in json_abi_typed:
            if entry["type"] == "constructor":
                if constructor:
                    raise ValueError("JSON ABI contains more than one constructor declarations")
                constructor = Constructor.from_json(entry)

            elif entry["type"] == "function":
                method = Method.from_json(entry)
                if entry["name"] in methods:
                    methods[entry["name"]] = methods[entry["name"]].with_method(method)
                else:
                    methods[entry["name"]] = method

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
            methods=methods.values(),
            events=events.values(),
            errors=errors.values(),
        )

    def __init__(
        self,
        constructor: None | Constructor = None,
        fallback: None | Fallback = None,
        receive: None | Receive = None,
        methods: None | Iterable[Method | MultiMethod] = None,
        events: None | Iterable[Event] = None,
        errors: None | Iterable[Error] = None,
    ):
        if constructor is None:
            constructor = Constructor(inputs=[])

        self.fallback = fallback
        self.receive = receive
        self.constructor = constructor
        self.method = Methods({method.name: method for method in (methods or [])})
        self.event = Methods({event.name: event for event in (events or [])})
        self.error = Methods({error.name: error for error in (errors or [])})

        self._error_by_selector = {
            error.selector: error for error in chain([PANIC_ERROR, LEGACY_ERROR], self.error)
        }

    def resolve_error(self, error_data: bytes) -> tuple[Error, dict[str, Any]]:
        """
        Given the packed error data, attempts to find the error in the ABI
        and decode the data into its fields.
        """
        if len(error_data) < SELECTOR_LENGTH:
            raise ValueError("Error data too short to contain a selector")

        selector, data = error_data[:SELECTOR_LENGTH], error_data[SELECTOR_LENGTH:]

        if selector in self._error_by_selector:
            error = self._error_by_selector[selector]
            decoded = error.decode_fields(data)
            return error, decoded

        raise UnknownError(f"Could not find an error with selector {selector.hex()} in the ABI")

    def __str__(self) -> str:
        all_methods: Iterable[
            Constructor | Fallback | Receive | Method | MultiMethod | Event | Error
        ] = chain(
            [self.constructor] if self.constructor else [],
            [self.fallback] if self.fallback else [],
            [self.receive] if self.receive else [],
            self.method,
            self.event,
            self.error,
        )

        indent = "    "

        def to_str(item: Any) -> str:
            if isinstance(item, MultiMethod):
                return ("\n" + indent).join(str(method) for method in item.methods.values())
            return str(item)

        method_list = [indent + to_str(method) for method in all_methods]
        return "{\n" + "\n".join(method_list) + "\n}"
