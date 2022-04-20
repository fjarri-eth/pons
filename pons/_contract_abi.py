from abc import ABC, abstractmethod
from collections import defaultdict
from enum import Enum, auto
from functools import cached_property
import inspect
import re
from typing import (
    Any, Tuple, Iterable, List, Dict, Optional, Union, Mapping,
    Iterable, TypeVar, Generic, Iterator, Sequence)

from eth_utils import keccak
from eth_abi import encode_single, decode_single

from ._abi_types import Type, dispatch_types


class StateMutability(Enum):
    PURE = auto()
    VIEW = auto()
    NONPAYABLE = auto()
    PAYABLE = auto()

    @classmethod
    def from_string(cls, val) -> 'StateMutability':
        state_mutability_values = {
            'pure': StateMutability.PURE,
            'view': StateMutability.VIEW,
            'nonpayable': StateMutability.NONPAYABLE,
            'payable': StateMutability.PAYABLE,
        }

        if val not in state_mutability_values:
            raise ValueError(f"Unknown state mutability type: `{val}`")

        return state_mutability_values[val]


class Signature:
    """
    Generalized signature of either inputs or outputs.
    """

    def __init__(self, parameters: Union[Mapping[str, Type], Sequence[Type]]):
        self._parameters = parameters
        self._signature: Optional[inspect.Signature] = None
        self._named_params = False

        if isinstance(parameters, Mapping):
            self._named_params = True
            self._signature = inspect.Signature(parameters=[
                inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                for name in parameters])
            types = list(parameters.values())
        else:
            types = list(parameters)

        self._types = types

    def _bind(self, *args, **kwargs) -> Tuple[Any, ...]:
        if self._signature:
            bargs = self._signature.bind(*args, **kwargs)
            return bargs.args
        else:
            assert not kwargs
            assert len(args) == len(self._parameters)
            return args

    @cached_property
    def canonical_form(self) -> str:
        """
        Returns the signature serialized in the canonical form as a string.
        """
        return "(" + ",".join(tp.canonical_form() for tp in self._types) + ")"

    def encode(self, *args, **kwargs) -> bytes:
        """
        Encodes assorted positional/keyword arguments into the bytestring
        according to the ABI format.
        """
        bound_args = self._bind(*args, **kwargs)
        normalized_values = [tp.normalize(arg) for arg, tp in zip(bound_args, self._types)]
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
        if isinstance(value, dict) and self._named_params:
            return self.encode(**value)
        elif isinstance(value, Iterable) and not self._named_params:
            return self.encode(*value)
        elif not self._named_params:
            return self.encode(value)
        else:
            raise TypeError(
                f"Wrong value type to encode ({type(value)}) "
                f"for a signature with" + ("named" if self._named_params else "anonymous") + " parameters")

    def decode(self, value_bytes: bytes) -> List[Any]:
        """
        Decodes the packed bytestring into a list of values.
        """
        normalized_values = decode_single(self.canonical_form, value_bytes)
        return [tp.denormalize(result) for result, tp in zip(normalized_values, self._types)]


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

    payable: bool
    """Whether this method is marked as payable"""

    @classmethod
    def from_json(cls, method_entry: dict) -> 'Constructor':
        """
        Creates this object from a JSON ABI method entry.
        """
        assert method_entry['type'] == 'constructor'
        assert 'name' not in method_entry
        assert 'outputs' not in method_entry or not method_entry['outputs']
        state_mutability = StateMutability.from_string(method_entry['stateMutability'])
        assert state_mutability in (StateMutability.NONPAYABLE, StateMutability.PAYABLE)
        inputs = dispatch_types(method_entry['inputs'])
        payable = state_mutability == StateMutability.PAYABLE
        return cls(inputs, payable=payable)

    def __init__(self, inputs: Mapping[str, Type], payable: bool = False):
        self.inputs = Signature(inputs)
        self.payable = payable

    def __call__(self, *args, **kwargs) -> 'ConstructorCall':
        """
        Returns an encoded call with given arguments.
        """
        input_bytes = self.inputs.encode(*args, *kwargs)
        return ConstructorCall(input_bytes)


class ReadMethod(Method):
    """
    A non-mutating contract method.
    """

    @classmethod
    def from_json(cls, method_entry: dict) -> 'ReadMethod':
        """
        Creates this object from a JSON ABI method entry.
        """
        outputs: Union[Dict[str, Type], List[Type]]
        name = method_entry['name']
        inputs = dispatch_types(method_entry['inputs'])
        outputs = dispatch_types(method_entry['outputs'])
        state_mutability = StateMutability.from_string(method_entry['stateMutability'])
        assert state_mutability in (StateMutability.PURE, StateMutability.VIEW)
        # The JSON ABI will have outputs in a dictionary even if they're anonymous.
        # We need to be stricter.
        if all(output == "" for output in outputs):
            outputs = list(outputs.values())
        return cls(name=name, inputs=inputs, outputs=outputs)

    def __init__(self, name: str, inputs: Mapping[str, Type], outputs: Union[Mapping[str, Type], Sequence[Type], Type]):
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

    def __call__(self, *args, **kwargs) -> 'ReadCall':
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


class WriteMethod(Method):
    """
    A mutating contract method.
    """

    payable: bool
    """Whether this method is marked as payable"""

    @classmethod
    def from_json(cls, method_entry: dict) -> 'WriteMethod':
        """
        Creates this object from a JSON ABI method entry.
        """
        name = method_entry['name']
        inputs = dispatch_types(method_entry['inputs'])
        assert 'outputs' not in method_entry or not method_entry['outputs']
        state_mutability = StateMutability.from_string(method_entry['stateMutability'])
        assert state_mutability in (StateMutability.NONPAYABLE, StateMutability.PAYABLE)
        payable = state_mutability == StateMutability.PAYABLE
        return cls(name=name, inputs=inputs, payable=payable)

    def __init__(self, name: str, inputs: Mapping[str, Type], payable: bool = False):
        self._name = name
        self._inputs = Signature(inputs)
        self.payable = payable

    @property
    def name(self) -> str:
        return self._name

    @property
    def inputs(self) -> Signature:
        return self._inputs

    def __call__(self, *args, **kwargs) -> 'WriteCall':
        """
        Returns an encoded call with given arguments.
        """
        return WriteCall(self._encode_call(*args, **kwargs))


class Fallback:
    """
    A fallback method.
    """

    payable: bool
    """Whether this method is marked as payable"""

    @classmethod
    def from_json(cls, entry) -> 'Fallback':
        """
        Creates this object from a JSON ABI method entry.
        """
        assert entry['type'] == 'fallback'
        assert 'name' not in entry
        assert 'inputs' not in entry
        assert 'outputs' not in entry
        state_mutability = StateMutability.from_string(entry['stateMutability'])
        assert state_mutability in (StateMutability.NONPAYABLE, StateMutability.PAYABLE)
        payable = state_mutability == StateMutability.PAYABLE
        return cls(payable)

    def __init__(self, payable: bool = False):
        self.payable = payable


class Receive:
    """
    A receive method.
    """

    payable: bool
    """Whether this method is marked as payable"""

    @classmethod
    def from_json(cls, entry) -> 'Receive':
        """
        Creates this object from a JSON ABI method entry.
        """
        assert entry['type'] == 'receive'
        assert 'name' not in entry
        assert 'inputs' not in entry
        assert 'outputs' not in entry
        state_mutability = StateMutability.from_string(entry['stateMutability'])
        assert state_mutability in (StateMutability.NONPAYABLE, StateMutability.PAYABLE)
        payable = state_mutability == StateMutability.PAYABLE
        return cls(payable)

    def __init__(self, payable: bool = False):
        self.payable = payable


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


MethodType = TypeVar('MethodType')


class Methods(Generic[MethodType]):
    """
    A holder for named methods which can be accessed as attributes,
    or iterated over.
    """

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

    Contract methods accessible as attributes of this object, with the type :py:class:`Method`.
    """

    constructor: Optional[Constructor]
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
    def from_json(cls, json_abi: list) -> 'ContractABI':
        constructor = None
        fallback = None
        receive = None
        read = []
        write = []
        methods = set()

        for entry in json_abi:

            if entry['type'] == 'constructor':
                if constructor:
                    raise ValueError("JSON ABI contains more than one constructor declarations")
                constructor = Constructor.from_json(entry)

            elif entry['type'] == 'function':
                if entry['name'] in methods:
                    # TODO: add support for overloaded methods
                    raise ValueError(
                        f"JSON ABI contains more than one declarations of `{entry['name']}`")

                methods.add(entry['name'])

                state_mutability = StateMutability.from_string(entry['stateMutability'])
                if state_mutability in (StateMutability.PURE, StateMutability.VIEW):
                    read.append(ReadMethod.from_json(entry))
                else:
                    write.append(WriteMethod.from_json(entry))

            elif entry['type'] == 'fallback':
                if fallback:
                    raise ValueError("JSON ABI contains more than one fallback declarations")
                fallback = Fallback.from_json(entry)

            elif entry['type'] == 'receive':
                if receive:
                    raise ValueError("JSON ABI contains more than one receive method declarations")
                receive = Receive.from_json(entry)

            elif entry['type'] == 'event':
                # TODO: support this
                pass

            else:
                raise ValueError(f"Unknown ABI entry type: {entry['type']}")

        return cls(
            constructor=constructor, fallback=fallback, receive=receive,
            read=read, write=write)

    def __init__(
            self,
            constructor: Optional[Constructor] = None,
            fallback: Optional[Fallback] = None,
            receive: Optional[Receive] = None,
            read: Optional[Iterable[ReadMethod]] = None,
            write: Optional[Iterable[WriteMethod]] = None
            ):
        self.fallback = fallback
        self.receive = receive
        self.constructor = constructor
        self.read = Methods({method.name: method for method in (read or [])})
        self.write = Methods({method.name: method for method in (write or [])})

    def __str__(self):
        all_methods = (
            ([self.constructor] if self.constructor else []) +
            ([self.fallback] if self.fallback else []) +
            ([self.receive] if self.receive else []) +
            list(self.read) +
            list(self.write))
        method_list = ["    " + str(method) for method in all_methods]
        return "{\n" + "\n".join(method_list) + "\n}"
