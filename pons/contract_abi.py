from abc import ABC, abstractmethod
from collections import defaultdict
from enum import Enum, auto
from functools import cached_property
import inspect
import re
from typing import Any, Tuple, Iterable, List, Dict, Optional

from eth_utils import keccak
from eth_abi import encode_single, decode_single

from .contract_types import Type, dispatch_types


class StateMutability(Enum):
    PURE = auto()
    VIEW = auto()
    NONPAYABLE = auto()
    PAYABLE = auto()

    @classmethod
    def from_string(cls, val):
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

    def __init__(self, parameters):
        self._parameters = parameters

        if isinstance(parameters, dict):
            self._named_params = True
            self._signature = inspect.Signature(parameters=[
                inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                for name in parameters])
            self._types = parameters.values()
        else:
            self._named_params = False
            self._signature = None
            self._types = parameters

    def bind(self, *args, **kwargs):
        if self._signature:
            bargs = self._signature.bind(*args, **kwargs)
            return bargs.args
        else:
            assert not kwargs
            assert len(args) == len(self._parameters)
            return args

    @cached_property
    def canonical_form(self):
        return "(" + ",".join(tp.canonical_form() for tp in self._types) + ")"

    def encode(self, *args, **kwargs):
        bound_args = self.bind(*args, **kwargs)
        normalized_values = [tp.normalize(arg) for arg, tp in zip(bound_args, self._types)]
        return encode_single(self.canonical_form, normalized_values)

    def encode_single(self, value):
        if isinstance(value, dict) and self._named_params:
            return self.encode(**value)
        elif isinstance(value, (list, tuple)) and not self._named_params:
            return self.encode(*value)
        elif not self._named_params:
            return self.encode(value)
        else:
            raise TypeError(
                f"Wrong value type to encode ({type(value)}) "
                f"for a signature with" + ("named" if self._named_parms else "anonymous") + " parameters")

    def decode(self, value_bytes: bytes):
        normalized_values = decode_single(self.canonical_form, value_bytes)
        return [tp.denormalize(result) for result, tp in zip(normalized_values, self._types)]


class Method(ABC):

    @property
    @abstractmethod
    def name(self):
        ...

    @property
    def inputs(self):
        ...

    @cached_property
    def selector(self):
        return keccak(self.name.encode() + self.inputs.canonical_form.encode())[:4]

    def _encode_call(self, *args, **kwargs):
        input_bytes = self.inputs.encode(*args, *kwargs)
        return self.selector + input_bytes


class Constructor:

    @classmethod
    def from_json(cls, method_entry: dict):
        assert method_entry['type'] == 'constructor'
        assert 'name' not in method_entry
        assert 'outputs' not in method_entry or not method_entry['outputs']
        state_mutability = StateMutability.from_string(method_entry['stateMutability'])
        assert state_mutability in (StateMutability.NONPAYABLE, StateMutability.PAYABLE)
        inputs = dispatch_types(method_entry['inputs'])
        payable = state_mutability == StateMutability.PAYABLE
        return cls(inputs, payable=payable)

    def __init__(self, inputs, payable=False):
        self.inputs = Signature(inputs)
        self.payable = payable

    def __call__(self, *args, **kwargs):
        input_bytes = self.inputs.encode(*args, *kwargs)
        return ConstructorCall(input_bytes)


class ReadMethod(Method):

    @classmethod
    def from_json(cls, method_entry: dict):
        name = method_entry['name']
        inputs = dispatch_types(method_entry['inputs'])
        outputs = dispatch_types(method_entry['outputs'])
        state_mutability = StateMutability.from_string(method_entry['stateMutability'])
        assert state_mutability in (StateMutability.PURE, StateMutability.VIEW)
        # The JSON ABI will have outputs in a dictionary even if they're anonymous.
        # We need to be stricter.
        if all(output == "" for output in outputs):
            outputs = outputs.values()
        return cls(name=name, inputs=inputs, outputs=outputs)

    def __init__(self, name: str, inputs: Dict[str, Type], outputs: Dict[str, Type]):
        self._name = name
        self._inputs = Signature(inputs)

        if isinstance(outputs, Type):
            outputs = [outputs]
            self._single_output = True
        else:
            self._single_output = False

        self.outputs = Signature(outputs)

    @property
    def name(self):
        return self._name

    @property
    def inputs(self):
        return self._inputs

    def __call__(self, *args, **kwargs):
        return ReadCall(self._encode_call(*args, **kwargs))

    def decode_output(self, output_bytes: bytes) -> Any:
        results = self.outputs.decode(output_bytes)
        if self._single_output:
            results = results[0]
        return results


class WriteMethod(Method):

    @classmethod
    def from_json(cls, method_entry: dict):
        name = method_entry['name']
        inputs = dispatch_types(method_entry['inputs'])
        assert 'outputs' not in method_entry or not method_entry['outputs']
        state_mutability = StateMutability.from_string(method_entry['stateMutability'])
        assert state_mutability in (StateMutability.NONPAYABLE, StateMutability.PAYABLE)
        payable = state_mutability == StateMutability.PAYABLE
        return cls(name=name, inputs=inputs, payable=payable)

    def __init__(
            self,
            name: str,
            inputs: Dict[str, Type],
            payable: bool = False):
        self._name = name
        self._inputs = Signature(inputs)
        self.payable = payable

    @property
    def name(self):
        return self._name

    @property
    def inputs(self):
        return self._inputs

    def __call__(self, *args, **kwargs):
        return WriteCall(self._encode_call(*args, **kwargs))


class Fallback:

    @classmethod
    def from_json(cls, entry):
        assert entry['type'] == 'fallback'
        assert 'name' not in entry
        assert 'inputs' not in entry
        assert 'outputs' not in entry
        state_mutability = StateMutability.from_string(entry['stateMutability'])
        assert state_mutability in (StateMutability.NONPAYABLE, StateMutability.PAYABLE)
        return cls(state_mutability)

    def __init__(self, state_mutability):
        self.state_mutability = state_mutability


class Receive:

    @classmethod
    def from_json(cls, entry):
        assert entry['type'] == 'receive'
        assert 'name' not in entry
        assert 'inputs' not in entry
        assert 'outputs' not in entry
        state_mutability = StateMutability.from_string(entry['stateMutability'])
        assert state_mutability in (StateMutability.NONPAYABLE, StateMutability.PAYABLE)
        return cls(state_mutability)

    def __init__(self, state_mutability):
        self.state_mutability = state_mutability


class ConstructorCall:

    def __init__(self, input_bytes):
        self.input_bytes = input_bytes


class ReadCall:

    def __init__(self, data_bytes):
        self.data_bytes = data_bytes


class WriteCall:

    def __init__(self, data_bytes):
        self.data_bytes = data_bytes


class Methods:

    def __init__(self, methods_dict):
        self._methods_dict = methods_dict

    def __getattr__(self, method_name) -> Method:
        return self._methods_dict[method_name]

    def __iter__(self):
        return iter(self._methods_dict.values())


class ContractABI:
    """
    A wrapper for contract ABI.

    Contract methods accessible as attributes of this object, with the type :py:class:`Method`.
    """

    @classmethod
    def from_json(cls, json_abi: list):
        constructor = None
        fallback = None
        receive = None
        methods = {}

        for entry in json_abi:

            if entry['type'] == 'constructor':
                if constructor:
                    raise ValueError("JSON ABI contains more than one constructor declarations")
                constructor = Constructor.from_json(entry)

            elif entry['type'] == 'function':
                state_mutability = StateMutability.from_string(entry['stateMutability'])
                if state_mutability in (StateMutability.PURE, StateMutability.VIEW):
                    method = ReadMethod.from_json(entry)
                else:
                    method = WriteMethod.from_json(entry)

                if method.name in methods:
                    # TODO: add support for overloaded methods
                    raise ValueError(
                        f"JSON ABI contains more than one declarations of `{method.name}`")

                methods[method.name] = method

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

        read = [method for method in methods.values() if isinstance(method, ReadMethod)]
        write = [method for method in methods.values() if isinstance(method, WriteMethod)]

        return cls(
            constructor=constructor, fallback=fallback, receive=receive,
            read=read, write=write)

    def __init__(self, constructor=None, fallback=False, receive=False, read=None, write=None):
        self.fallback = fallback
        self.receive = receive
        self.constructor = constructor
        self.read = Methods({method.name: method for method in (read or [])})
        self.write = Methods({method.name: method for method in (write or [])})

    def __str__(self):
        all_methods = (
            ([self.constructor] if self.constructor else []) +
            ([self.fallback] if self.fallback else [])
            ([self.receive] if self.receive else [])
            + self._functions)
        method_list = ["    " + str(method) for method in all_methods]
        return "{\n" + "\n".join(method_list) + "\n}"
