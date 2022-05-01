from abc import ABC, abstractmethod
from functools import cached_property
import inspect
from typing import (
    Any,
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
)

from eth_utils import keccak
from eth_abi import encode_single, decode_single
from eth_abi.exceptions import DecodingError as BackendDecodingError

from ._abi_types import Type, dispatch_types, dispatch_type


class ABIDecodingError(Exception):
    """
    Raised on an error when decoding a value in an Eth ABI encoded bytestring.
    """


class Signature:
    """
    Generalized signature of either inputs or outputs.
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
        normalized_values = [tp.normalize(arg) for arg, tp in zip(bound_args.args, self._types)]
        return encode_single(self.canonical_form, normalized_values)

    def encode_single(self, value) -> bytes:
        """
        Encodes a single value into the bytestring according to the ABI format.

        If the signature has named parameters, the value is treated
        as a dictionary of keyword arguments.
        If the signature has anonymous parameters, and the value is an iterable,
        it is treated as alist of positional arguments;
        if it is not iterable, it is treated as a single positional argument.
        """
        if isinstance(value, Mapping):
            return self.encode(**value)
        elif isinstance(value, Iterable):
            return self.encode(*value)
        else:
            return self.encode(value)

    def decode(self, value_bytes: bytes) -> List[Any]:
        """
        Decodes the packed bytestring into a list of values.
        """
        try:
            normalized_values = decode_single(self.canonical_form, value_bytes)
        except BackendDecodingError as exc:
            # wrap possible `eth_abi` errors
            message = (
                f"Could not decode the return value "
                f"with the expected signature {self.canonical_form}: {str(exc)}"
            )
            raise ABIDecodingError(message) from exc

        return [tp.denormalize(result) for result, tp in zip(normalized_values, self._types)]

    def __str__(self):
        if self._named_parameters:
            params = ", ".join(
                f"{tp.canonical_form} {name}"
                for name, tp in zip(self._signature.parameters, self._types)
            )
        else:
            params = ", ".join(f"{tp.canonical_form}" for tp in self._types)
        return f"({params})"


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
        results = self.outputs.decode(output_bytes)
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

    @classmethod
    def from_json(cls, json_abi: list) -> "ContractABI":
        constructor = None
        fallback = None
        receive = None
        read = []
        write = []
        methods = set()

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

            else:
                raise ValueError(f"Unknown ABI entry type: {entry['type']}")

        return cls(
            constructor=constructor,
            fallback=fallback,
            receive=receive,
            read=read,
            write=write,
        )

    def __init__(
        self,
        constructor: Optional[Constructor] = None,
        fallback: Optional[Fallback] = None,
        receive: Optional[Receive] = None,
        read: Optional[Iterable[ReadMethod]] = None,
        write: Optional[Iterable[WriteMethod]] = None,
    ):

        if constructor is None:
            constructor = Constructor(inputs=[])

        self.fallback = fallback
        self.receive = receive
        self.constructor = constructor
        self.read = Methods({method.name: method for method in (read or [])})
        self.write = Methods({method.name: method for method in (write or [])})

    def __str__(self):
        all_methods = (
            ([self.constructor] if self.constructor else [])
            + ([self.fallback] if self.fallback else [])
            + ([self.receive] if self.receive else [])
            + list(self.read)
            + list(self.write)
        )
        method_list = ["    " + str(method) for method in all_methods]
        return "{\n" + "\n".join(method_list) + "\n}"
