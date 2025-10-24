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
from ._abi_types import ABI_JSON, Type, decode_args, dispatch_parameter_types, encode_args

# Anonymous events can have at most 4 indexed fields
ANONYMOUS_EVENT_INDEXED_FIELDS = 4

# Anonymous events can have at most 4 indexed fields
EVENT_INDEXED_FIELDS = 3

# The number of bytes in a function selector.
SELECTOR_LENGTH = 4


class FieldValues:
    """
    A container for field values of an event, error, or a method return.

    Since Solidity allows fields at arbitrary positions to be anonymous,
    a dictionary cannot handle all the possibilities.
    """

    def __init__(self, values: Sequence[tuple[str | None, Any]]):
        names = [name for name, _value in values if name is not None]
        if len(names) != len(set(names)):
            raise ValueError("The values cannot have repeating names")

        self._values_seq = values
        self._values_dict = {name: value for name, value in values if name is not None}
        self._representable_as_dict = len(names) == len(self._values_seq)

    @property
    def as_dict(self) -> dict[str, Any]:
        """
        Returns the equivalent dictionary representation.

        Raises ``ValueError`` if there are anonymous fields present.
        """
        if not self._representable_as_dict:
            raise ValueError(
                "This structure has some anonymous fields "
                "and therefore is not representable as a `dict`"
            )
        return self._values_dict

    @cached_property
    def as_tuple(self) -> tuple[Any, ...]:
        """
        Returns the equivalent tuple representation
        (a tuple of the values with the field names omitted).
        """
        return tuple(item for _name, item in self._values_seq)

    def __getitem__(self, name: str) -> Any:
        """Returns the value with the given name."""
        return self._values_dict[name]

    def __getattr__(self, name: str) -> Any:
        """Returns the value with the given name."""
        return self._values_dict[name]

    def __repr__(self) -> str:
        return f"FieldValues({self._values_seq!r})"


class Fields:
    """
    Describes a sequence of optionally named typed values.
    These can be method parameters, method outputs, error fields,
    or event fields.
    """

    names: tuple[str | None, ...]
    """Field names."""

    types: tuple[Type, ...]
    """Field types."""

    def __init__(
        self, fields: Mapping[str, Type] | Sequence[Type] | Sequence[tuple[str | None, Type]]
    ):
        names: tuple[str | None, ...]
        if isinstance(fields, Mapping):
            names = tuple(fields)
            types = tuple(fields.values())
        elif all(isinstance(elem, Type) for elem in fields):
            fields = cast("Sequence[Type]", fields)
            names = tuple(None for tp in fields)
            types = tuple(fields)
        else:
            fields = cast("Sequence[tuple[str | None, Type]]", fields)
            names = tuple(name for name, _tp in fields)
            types = tuple(tp for _name, tp in fields)

        self.names = names
        self.types = types

    @cached_property
    def named_fields(self) -> set[str]:
        return {name for name in self.names if name is not None}

    @cached_property
    def as_signature(self) -> inspect.Signature:
        """
        Returns the fields represented as a signature.

        .. note::

            In Solidity, it is possible to have named and anonymous method parameters
            or event/error fields in arbitrary order.
            This cannot be mapped to Python function signatures.
            Also it is possible that some parameter names are Python keywords,
            so they will be rejected by the Signature constructor.

            So the keyword names will be postfixed with a `_`,
            and anonymous fields will be given auto-generated names.
        """
        # Keep as many original names as possible
        existing_names = {name for name in self.names if name is not None and not iskeyword(name)}

        safe_names = []
        disambiguation_counter = 1
        for arg_num, name in enumerate(self.names):
            if name is None:
                base_name = "_" + str(arg_num + 1)
            elif iskeyword(name):
                base_name = name + "_"
            else:
                safe_names.append(name)
                continue

            # Since we renamed an existing name, there can potentially be
            # an existing one equal to it.

            safe_name = base_name
            while safe_name in existing_names:
                safe_name = base_name + "_" + str(disambiguation_counter)
                disambiguation_counter += 1

            safe_names.append(safe_name)

        return inspect.Signature(
            parameters=[
                inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                for name in safe_names
            ]
        )

    @cached_property
    def canonical_form(self) -> str:
        """Returns the field types serialized in the canonical form as a string."""
        return "(" + ",".join(tp.canonical_form for tp in self.types) + ")"

    def encode(self, values: Iterable[Any]) -> bytes:
        """Encodes the given position values into bytes according to field types."""
        return encode_args(*zip(self.types, values, strict=True))

    def decode(self, value_bytes: bytes) -> FieldValues:
        """
        Decodes the packed bytestring into a list of pairs
        of the original parameter/field name and the value.
        """
        return FieldValues(list(zip(self.names, decode_args(self.types, value_bytes), strict=True)))

    def to_json(self) -> ABI_JSON:
        """Returns this object's JSON ABI."""
        args = []
        for name, tp in zip(self.names, self.types, strict=True):
            args.append(
                {
                    "name": name if name is not None else "",
                    "type": tp.canonical_form,
                }
            )
        return args

    def __str__(self) -> str:
        fields = ", ".join(
            tp.canonical_form + ((" " + name) if name is not None else "")
            for name, tp in zip(self.names, self.types, strict=True)
        )
        return f"({fields})"


class Either:
    """Denotes an `OR` operation when filtering events."""

    def __init__(self, *items: Any):
        self.items = items


class EventFields(Fields):
    """Fields of an event structure."""

    indexed: tuple[bool, ...]
    """A sequence indicating whether the field at the given position is indexed."""

    def __init__(
        self,
        fields: Mapping[str, Type] | Sequence[Type] | Sequence[tuple[str | None, Type]],
        indexed: AbstractSet[str] | Sequence[bool],
    ):
        super().__init__(fields)

        self._signature = self.as_signature

        # Unique names for each field, will be used for internal field identification.
        self._safe_names = tuple(self._signature.parameters)

        if isinstance(indexed, AbstractSet):
            if not set(indexed).issubset(self.named_fields):
                raise ValueError("All the names in `indexed` must be present in the fields list")
            indexed_seq = tuple(name in indexed for name in self._signature.parameters)
        else:
            indexed_seq = tuple(indexed)
            if len(indexed_seq) != len(self.names):
                raise ValueError(
                    "If `indexed` is a sequence of booleans, "
                    "its length must match the number of fields"
                )

        self.indexed = indexed_seq

        # Need to preserve the order of the names that was declared when creating the signature.
        self._indexed_names = [
            name for name, indexed in zip(self._safe_names, indexed_seq, strict=True) if indexed
        ]
        self._indexed_types = [
            tp for tp, indexed in zip(self.types, indexed_seq, strict=True) if indexed
        ]

        self._nonindexed_names = [
            name for name, indexed in zip(self._safe_names, indexed_seq, strict=True) if not indexed
        ]
        self._nonindexed_types = [
            tp for tp, indexed in zip(self.types, indexed_seq, strict=True) if not indexed
        ]

    def encode_to_topics(self, *args: Any, **kwargs: Any) -> tuple[None | tuple[bytes, ...], ...]:
        """
        Binds given arguments to event's indexed parameters
        and encodes them as log topics.

        .. note::

            If keyword arguments are used, any field names that matched Python keywords
            need to be postfixed by a `_`.
        """
        bound_args = self._signature.bind_partial(*args, **kwargs)

        encoded_topics: list[None | tuple[bytes, ...]] = []
        for safe_name, tp in zip(self._safe_names, self.types, strict=True):
            if safe_name not in bound_args.arguments:
                encoded_topics.append(None)
                continue

            bound_val = bound_args.arguments[safe_name]

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

    def decode_log_entry(self, topics: Sequence[bytes], data: bytes) -> FieldValues:
        """Decodes the event fields from the given log entry data."""
        if len(topics) != len(self._indexed_names):
            raise ValueError(
                f"The number of topics in the log entry ({len(topics)}) does not match "
                f"the number of indexed fields in the event ({len(self._indexed_names)})"
            )

        decoded_topics: dict[str, Any] = {
            name: tp.decode_from_topic(topic)
            for name, tp, topic in zip(
                self._indexed_names, self._indexed_types, topics, strict=True
            )
        }

        decoded_data_tuple = decode_args(self._nonindexed_types, data)
        decoded_nonindexed = dict(zip(self._nonindexed_names, decoded_data_tuple, strict=True))

        # Assemble preserving the field order
        decoded_data = []
        for safe_name, name in zip(self._safe_names, self.names, strict=True):
            if safe_name in decoded_topics:
                decoded_data.append((name, decoded_topics[safe_name]))
            else:
                decoded_data.append((name, decoded_nonindexed[safe_name]))

        return FieldValues(decoded_data)

    def to_json(self) -> ABI_JSON:
        """Returns this object's JSON ABI."""
        args: list[ABI_JSON] = []
        for name, tp, indexed in zip(self.names, self.types, self.indexed, strict=True):
            args.append(
                {
                    "indexed": indexed,
                    "name": name if name is not None else "",
                    "type": tp.canonical_form,
                }
            )
        return args

    def __str__(self) -> str:
        params = []
        for name, tp, indexed in zip(self.names, self.types, self.indexed, strict=True):
            indexed_str = " indexed" if indexed else ""
            name_str = (" " + name) if name is not None else ""
            params.append(f"{tp.canonical_form}{indexed_str}{name_str}")
        return "(" + ", ".join(params) + ")"


class Constructor:
    """
    Contract constructor.

    .. note::

       If the name of a parameter given to the constructor matches a Python keyword,
       ``_`` will be appended to it.
    """

    inputs: Fields
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
        inputs = dispatch_parameter_types(method_entry_typed.get("inputs", []))
        payable = method_entry_typed["stateMutability"] == "payable"
        return cls(inputs, payable=payable)

    def __init__(
        self,
        inputs: Mapping[str, Type] | Sequence[tuple[str | None, Type]],
        *,
        payable: bool = False,
    ):
        self.inputs = Fields(inputs)
        self._inputs_signature = self.inputs.as_signature
        self.payable = payable

    def __call__(self, *args: Any, **kwargs: Any) -> "ConstructorCall":
        """Returns an encoded call with given arguments."""
        input_bytes = self.inputs.encode(self._inputs_signature.bind(*args, **kwargs).args)
        return ConstructorCall(input_bytes)

    def to_json(self) -> ABI_JSON:
        """Returns this object's JSON ABI."""
        return {
            "type": "constructor",
            "stateMutability": "payable" if self.payable else "nonpayable",
            "inputs": self.inputs.to_json(),
        }

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

    inputs: Fields
    """The input signature of this method."""

    outputs: Fields
    """The output signature of this method."""

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
        inputs = dispatch_parameter_types(method_entry_typed["inputs"])

        mutability = Mutability.from_json(method_entry_typed["stateMutability"])

        outputs: None | dict[str, Type] | list[tuple[str | None, Type]]
        if "outputs" not in method_entry_typed:
            outputs = None
        else:
            outputs = dispatch_parameter_types(method_entry_typed["outputs"])

        return cls(name=name, inputs=inputs, outputs=outputs, mutability=mutability)

    def __init__(
        self,
        name: str,
        mutability: Mutability,
        inputs: Mapping[str, Type] | Sequence[Type] | Sequence[tuple[str | None, Type]],
        outputs: None
        | Mapping[str, Type]
        | Sequence[Type]
        | Sequence[tuple[str | None, Type]]
        | Type = None,
    ):
        self.name = name
        self.inputs = Fields(inputs)
        self._inputs_signature = self.inputs.as_signature
        self._mutability = mutability
        self.payable = mutability.payable
        self.mutating = mutability.mutating

        if outputs is None:
            outputs = []
        if isinstance(outputs, Type):
            outputs = [(None, outputs)]

        self.outputs = Fields(outputs)

    def bind(self, *args: Any, **kwargs: Any) -> BoundArguments:
        """Binds the given arguments to the method's signature."""
        return self._inputs_signature.bind(*args, **kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> "MethodCall":
        """Returns an encoded call with given arguments."""
        bound_args = self.bind(*args, **kwargs)
        return self.call_bound(bound_args)

    def call_bound(self, bound_args: BoundArguments) -> "MethodCall":
        """Creates a method call object using previouosly bound arguments."""
        input_bytes = self.inputs.encode(bound_args.args)
        encoded = self.selector + input_bytes
        return MethodCall(self, encoded)

    @cached_property
    def selector(self) -> bytes:
        """Method's selector."""
        return keccak(self.name.encode() + self.inputs.canonical_form.encode())[:SELECTOR_LENGTH]

    def decode_output(self, output_bytes: bytes) -> Any:
        """
        Decodes the output from ABI-packed bytes.

        If there is only a single output, its value is returned.
        If all the fields in the output are unnamed, it is returned as a tuple of values.
        Otherwise it is returned as a :py:class:`FieldValues` object.
        """
        results = self.outputs.decode(output_bytes)

        if len(self.outputs.names) == 1:
            return results.as_tuple[0]
        if all(name is None for name in self.outputs.names):
            return results.as_tuple

        return results

    def with_method(self, method: "Method") -> "MultiMethod":
        """Returns a multimethod resulting from joining this method with `method`."""
        return MultiMethod(self, method)

    def to_json(self) -> ABI_JSON:
        """Returns this object's JSON ABI."""
        return {
            "type": "function",
            "name": self.name,
            "stateMutability": self._mutability.value,
            "inputs": self.inputs.to_json(),
            "outputs": self.outputs.to_json(),
        }

    def __str__(self) -> str:
        returns = "" if not self.outputs.names else f" returns {self.outputs}"
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
        (corresponding to :py:attr:`Fields.canonical_form`).
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

    def to_json(self) -> list[ABI_JSON]:
        """Returns this object's JSON ABI."""
        return [method.to_json() for method in self._methods.values()]

    def __str__(self) -> str:
        return "; ".join(str(method) for method in self._methods.values())


class Event:
    """
    A contract event.

    .. note::

       If the name of a field given to the constructor matches a Python keyword,
       ``_`` will be appended to it.
    """

    name: str
    """The name of this event."""

    fields: EventFields
    """The event fields."""

    anonymous: bool
    """Whether the event is anonymous."""

    @classmethod
    def from_json(cls, event_entry: ABI_JSON) -> "Event":
        """Creates this object from a JSON ABI method entry."""
        # TODO (#83): use proper validation
        event_entry_typed = cast("Mapping[str, Any]", event_entry)

        if event_entry_typed["type"] != "event":
            raise ValueError("Event object must be created from a JSON entry with type='event'")

        name = event_entry_typed["name"]
        fields = dispatch_parameter_types(event_entry_typed["inputs"])
        indexed = [input_["indexed"] for input_ in event_entry_typed["inputs"]]

        return cls(
            name=name, fields=fields, indexed=indexed, anonymous=event_entry_typed["anonymous"]
        )

    def __init__(
        self,
        name: str,
        fields: Mapping[str, Type] | Sequence[tuple[str | None, Type]],
        indexed: AbstractSet[str] | Sequence[bool],
        *,
        anonymous: bool = False,
    ):
        self.name = name
        self.fields = EventFields(fields, indexed)
        self.anonymous = anonymous

        indexed_num = sum(self.fields.indexed)

        if anonymous and indexed_num > ANONYMOUS_EVENT_INDEXED_FIELDS:
            raise ValueError(
                f"Anonymous events can have at most {ANONYMOUS_EVENT_INDEXED_FIELDS} indexed fields"
            )
        if not anonymous and indexed_num > EVENT_INDEXED_FIELDS:
            raise ValueError(
                f"Non-anonymous events can have at most {EVENT_INDEXED_FIELDS} indexed fields"
            )

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

    def decode_log_entry(self, log_entry: LogEntry) -> FieldValues:
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

    def to_json(self) -> ABI_JSON:
        """Returns this object's JSON ABI."""
        return {
            "type": "event",
            "name": self.name,
            "inputs": self.fields.to_json(),
            "anonymous": self.anonymous,
        }

    def __str__(self) -> str:
        return f"event {self.name}{self.fields}" + (" anonymous" if self.anonymous else "")


class EventFilter:
    """A filter for events coming from any contract address."""

    topics: tuple[None | tuple[LogTopic, ...], ...]

    def __init__(self, topics: tuple[None | tuple[LogTopic, ...], ...]):
        self.topics = topics


class Error:
    """A custom contract error."""

    name: str
    """The name of the error structure."""

    fields: Fields
    """The fields of the structure."""

    @classmethod
    def from_json(cls, error_entry: ABI_JSON) -> "Error":
        """Creates this object from a JSON ABI method entry."""
        # TODO (#83): use proper validation
        error_entry_typed = cast("Mapping[str, Any]", error_entry)

        if error_entry_typed["type"] != "error":
            raise ValueError("Error object must be created from a JSON entry with type='error'")

        name = error_entry_typed["name"]
        fields = dispatch_parameter_types(error_entry_typed["inputs"])

        return cls(name=name, fields=fields)

    def __init__(
        self,
        name: str,
        fields: Mapping[str, Type] | Sequence[Type] | Sequence[tuple[str | None, Type]],
    ):
        self.name = name
        self._named_fields = isinstance(fields, Mapping)
        self.fields = Fields(fields)

    @cached_property
    def selector(self) -> bytes:
        """Error's selector."""
        return keccak(self.name.encode() + self.fields.canonical_form.encode())[:SELECTOR_LENGTH]

    def decode_fields(self, data_bytes: bytes) -> FieldValues:
        """Decodes the error fields from the given packed data."""
        return self.fields.decode(data_bytes)

    def to_json(self) -> ABI_JSON:
        """Returns this object's JSON ABI."""
        return {
            "type": "error",
            "name": self.name,
            "inputs": self.fields.to_json(),
        }

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

    def to_json(self) -> ABI_JSON:
        """Returns this object's JSON ABI."""
        return {
            "type": "fallback",
            "stateMutability": "payable" if self.payable else "nonpayable",
        }

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
            raise ValueError("Receive object must be created from a JSON entry with type='receive'")
        if method_entry_typed["stateMutability"] not in ("nonpayable", "payable"):
            raise ValueError(
                "Receive method's JSON entry state mutability must be `nonpayable` or `payable`"
            )
        payable = method_entry_typed["stateMutability"] == "payable"
        return cls(payable=payable)

    def __init__(self, *, payable: bool = False):
        self.payable = payable

    def to_json(self) -> ABI_JSON:
        """Returns this object's JSON ABI."""
        return {
            "type": "receive",
            "stateMutability": "payable" if self.payable else "nonpayable",
        }

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

    def resolve_error(self, error_data: bytes) -> tuple[Error, FieldValues]:
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

    def to_json(self) -> ABI_JSON:
        """Returns the serialized list of contract items (methods, errors, events)."""
        all_items: Iterable[
            Constructor | Fallback | Receive | Method | MultiMethod | Event | Error
        ] = chain(
            [self.constructor] if self.constructor else [],
            [self.fallback] if self.fallback else [],
            [self.receive] if self.receive else [],
            self.method,
            self.event,
            self.error,
        )
        entries: list[ABI_JSON] = []
        for item in all_items:
            if isinstance(item, MultiMethod):
                entries.extend(item.to_json())
            else:
                entries.append(item.to_json())

        return entries

    def __str__(self) -> str:
        all_items: Iterable[
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

        method_list = [indent + to_str(method) for method in all_items]
        return "{\n" + "\n".join(method_list) + "\n}"
