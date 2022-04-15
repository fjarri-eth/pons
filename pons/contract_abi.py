from abc import ABC, abstractmethod
from collections import defaultdict
from enum import Enum, auto
import inspect
import re
from typing import Any, Tuple, Iterable, List, Dict, Optional

from eth_utils import keccak
from eth_abi import encode_single, decode_single

from .contract_types import Type, dispatch_type


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


class Callable(ABC):

    @property
    @abstractmethod
    def inputs(self):
        ...

    @property
    @abstractmethod
    def outputs(self):
        ...

    @abstractmethod
    def selector(self):
        ...

    def canonical_input_signature(self):
        return "(" + ",".join(param.canonical_form() for param in self.inputs.values()) + ")"

    def canonical_output_signature(self):
        return "(" + ",".join(param.canonical_form() for param in self.outputs.values()) + ")"

    def __call__(self, *args, **kwargs):
        return MethodCall(self, *args, **kwargs)


class Constructor(Callable):

    @classmethod
    def from_json(cls, method_entry: dict):
        assert method_entry['type'] == 'constructor'
        assert 'name' not in method_entry
        assert 'outputs' not in method_entry
        state_mutability = StateMutability.from_string(method_entry['stateMutability'])
        assert state_mutability in (StateMutability.NONPAYABLE, StateMutability.PAYABLE)
        inputs = {entry['name']: dispatch_type(entry) for entry in method_entry['inputs']}
        return cls(inputs, state_mutability)

    @classmethod
    def nonpayable(cls, *args, **kwds):
        return cls(*args, **kwds, state_mutability=StateMutability.NONPAYABLE)

    @classmethod
    def payable(cls, *args, **kwds):
        return cls(*args, **kwds, state_mutability=StateMutability.PAYABLE)

    def __init__(self, inputs, state_mutability):
        self._inputs = inputs
        self.state_mutability = state_mutability

    @property
    def inputs(self):
        return self._inputs

    @property
    def outputs(self):
        return []

    def selector(self):
        return b""


class Method(Callable):

    @classmethod
    def from_json(cls, method_entry: dict):
        name = method_entry['name']
        state_mutability = StateMutability.from_string(method_entry['stateMutability'])
        inputs = {entry['name']: dispatch_type(entry) for entry in method_entry['inputs']}
        outputs = {entry['name']: dispatch_type(entry) for entry in method_entry['inputs']}
        return cls(name=name, inputs=inputs, outputs=outputs, state_mutability=state_mutability)

    @classmethod
    def pure(cls, name, inputs, outputs, unique_name=None):
        return cls(name, inputs, outputs, state_mutability=StateMutability.PURE, unique_name=unique_name)

    @classmethod
    def view(cls, name, inputs, outputs, unique_name=None):
        return cls(name, inputs, outputs, state_mutability=StateMutability.VIEW, unique_name=unique_name)

    @classmethod
    def nonpayable(cls, name, inputs, unique_name=None):
        return cls(name, inputs, {}, state_mutability=StateMutability.NONPAYABLE, unique_name=unique_name)

    @classmethod
    def payable(cls, name, inputs, unique_name=None):
        return cls(name, inputs, {}, state_mutability=StateMutability.PAYABLE, unique_name=unique_name)

    def __init__(
            self,
            name: str,
            inputs: Dict[str, Type],
            outputs: List[Type],
            state_mutability: StateMutability,
            unique_name: Optional[str] = None):
        self.name = name
        self.unique_name = unique_name or name
        self.state_mutability = state_mutability
        self._inputs = inputs

        if isinstance(outputs, Type):
            outputs = dict(_=outputs)
        self._outputs = outputs

    def disambiguate(self):
        return type(self)(
            name=self.name,
            inputs=self._inputs,
            outputs=self._outputs,
            state_mutability=self.state_mutability,
            unique_name=self.name + '_' + self.selector().hex())

    @property
    def inputs(self):
        return self._inputs

    @property
    def outputs(self):
        return self._outputs

    def selector(self):
        signature = self.canonical_input_signature()
        return keccak(self.name.encode() + signature.encode())[:4]


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


class MethodCall:
    """
    A contract method with attached arguments.
    """

    args: Tuple
    """The unprocessed arguments to the method call."""


    def __init__(self, method, *args, **kwargs):

        signature = inspect.Signature(parameters=[
            inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            for name, tp in method.inputs.items()
            ])
        bargs = signature.bind(*args, **kwargs)
        normalized_args = [
            tp.normalize(barg)
            for barg, tp in zip(bargs.arguments.values(), method.inputs.values())
            ]

        self.method = method
        self.args = normalized_args

    def encode(self) -> bytes:
        signature = self.method.canonical_input_signature()
        encoded_args = encode_single(signature, self.args)
        return self.method.selector() + encoded_args

    def decode_output(self, output: bytes) -> Any:
        signature = self.method.canonical_output_signature()
        normalized_results = decode_single(signature, output)

        assert len(normalized_results) == len(self.method.outputs)

        results = [
            tp.denormalize(result)
            for result, tp in zip(normalized_results, self.method.outputs.values())
            ]

        # TODO: or always return a list?
        if len(results) == 1:
            results = results[0]
        return results


class Methods:

    def __init__(self, methods_dict):
        self._methods_dict = methods_dict

    def __getattr__(self, method_name) -> Method:
        return self._methods_dict[method_name]


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
        selectors = defaultdict(set)

        for entry in json_abi:

            if entry['type'] == 'constructor':
                if constructor:
                    raise ValueError("JSON ABI contains more than one constructor declarations")
                constructor = Constructor.from_json(entry)

            elif entry['type'] == 'function':
                method = Method.from_json(entry)
                selector = method.selector()
                if method.name in selectors:
                    if selector in selectors[method.name]:
                        raise ValueError(
                            f"JSON ABI contains more than one declarations of `{method.name}` "
                            f"with the same selector ({method})")

                    if len(selectors[method.name]) == 1:
                        # If it's the second encountered method, remove the "simple" entry
                        another_method = methods.pop(method.name)
                        another_method = another_method.disambiguate()
                        methods[another_method.unique_name] = another_method

                    method = method.disambiguate()

                selectors[method.name].add(selector)
                methods[method.unique_name] = method

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

        return cls(constructor=constructor, fallback=fallback, receive=receive, methods=methods.values())

    def __init__(self, constructor=None, fallback=False, receive=False, methods=None):
        self.fallback = fallback
        self.receive = receive
        self.constructor = constructor
        self.method = Methods({method.unique_name: method for method in methods})

    def __str__(self):
        all_methods = (
            ([self.constructor] if self.constructor else []) +
            ([self.fallback] if self.fallback else [])
            ([self.receive] if self.receive else [])
            + self._functions)
        method_list = ["    " + str(method) for method in all_methods]
        return "{\n" + "\n".join(method_list) + "\n}"
