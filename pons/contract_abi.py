from enum import Enum, auto
import re
from typing import Any, Tuple

from eth_utils import keccak
from eth_abi import encode_single, decode_single

from .primitive_types import type_from_abi_string


class StateMutability(Enum):
    PURE = auto()
    VIEW = auto()
    NONPAYABLE = auto()
    PAYABLE = auto()


class Parameter:

    def __init__(self, abi_entry):
        self.name = abi_entry['name'] or None
        self.type = dispatch_type(abi_entry)

    def canonical_signature(self):
        return self.type.canonical_signature()

    def __str__(self):
        if self.name:
            return f"{self.type} {self.name}"
        else:
            return str(self.type)


def dispatch_type(abi_entry):
    type_str = abi_entry['type']
    match = re.match(r"^(.*?)(\[(\d+)?\])?$", type_str)
    if not match:
        raise Exception(f"Incorrect type format: {type_str}")

    element_type_name = match.group(1)
    is_array = match.group(2)
    array_size = match.group(3)
    if array_size:
        array_size = int(array_size)

    if is_array:
        element_entry = dict(abi_entry)
        element_entry['type'] = element_type_name
        element_type = dispatch_type(element_entry)
        return Array(element_type, array_size)
    elif element_type_name == 'tuple':
        fields = {}
        for component in abi_entry['components']:
            fields[component['name']] = dispatch_type(component)
        return Struct(fields)
    else:
        return type_from_abi_string(element_type_name)

    self.is_array = is_array is not None
    self.array_size = array_size


class Array:

    def __init__(self, element_type, size):
        self.element_type = element_type
        self.size = size

    def canonical_signature(self):
        return self.element_type.canonical_signature() + "[" + (str(self.size) if self.size else "") + "]"

    def __str__(self):
        return str(self.element_type) + "[" + (str(self.size) if self.size else "") + "]"


class Struct:

    def __init__(self, fields):
        self.fields = fields

    def canonical_signature(self):
        return "(" + ",".join(field.canonical_signature() for field in self.fields.values()) + ")"

    def __str__(self):
        return "(" + ", ".join(str(tp) + " " + str(name) for name, tp in self.fields.items()) + ")"


class Method:
    """
    A contract method.
    """

    def __init__(self, abi_entry):

        self.is_constructor = abi_entry['type'] == 'constructor'
        self.is_fallback = abi_entry['type'] == 'fallback'

        state_mutability_values = {
            'pure': StateMutability.PURE,
            'view': StateMutability.VIEW,
            'nonpayable': StateMutability.NONPAYABLE,
            'payable': StateMutability.PAYABLE,
        }

        if abi_entry['stateMutability'] not in state_mutability_values:
            raise ValueError()

        self.state_mutability = state_mutability_values[abi_entry['stateMutability']]
        self.name = None if self.is_constructor else abi_entry['name']

        if 'outputs' in abi_entry:
            if abi_entry['outputs']:
                self.outputs = [Parameter(entry) for entry in abi_entry['outputs']]
            else:
                self.outputs = None
        else:
            self.outputs = None

        self.inputs = [Parameter(entry) for entry in abi_entry['inputs']]

    def canonical_input_signature(self):
        return "(" + ",".join(param.canonical_signature() for param in self.inputs) + ")"

    def canonical_output_signature(self):
        return "(" + ",".join(param.canonical_signature() for param in self.outputs) + ")"

    def id(self):
        signature = self.canonical_input_signature()
        return keccak(self.name.encode() + signature.encode())[:4]

    def __call__(self, *args) -> 'MethodCall':
        """
        Creates a method call object with encapsulated arguments.
        """
        # TODO: allow args/kwds and bind them to correct parameters using inspect.signature()
        # Possibly validate the internal structure here too?
        return MethodCall(self, args, is_constructor=self.is_constructor)

    def __str__(self):
        name = "constructor" if self.is_constructor else ("function " + self.name)
        params = ", ".join(str(param) for param in self.inputs)
        if self.outputs:
            returns_str = ", ".join(str(param) for param in self.outputs)
            returns = f" returns ({returns_str})"
        else:
            returns = ""
        return f"{name}({params}){returns}"


class MethodCall:
    """
    A contract method with attached arguments.
    """

    method_name: str
    """The name of the method."""

    args: Tuple
    """The unprocessed arguments to the method call."""


    def __init__(self, method, args, is_constructor=False):
        self._method = method
        self.args = args
        self._is_constructor = is_constructor
        self.method_name = method.name

    def encode(self) -> bytes:
        signature = self._method.canonical_input_signature()
        encoded_args = encode_single(signature, self.args)

        if not self._is_constructor:
            return self._method.id() + encoded_args
        else:
            return encoded_args

    def decode_output(self, output: bytes) -> Any:
        signature = self._method.canonical_output_signature()
        results = decode_single(signature, output)
        # TODO: or do it when deriving canonical_output_signature?
        if len(self._method.outputs) == 1:
            results = results[0]
        return results


class ContractABI:
    """
    A wrapper for contrat ABI.

    Contract methods accessible as attributes of this object, with the type :py:class:`Method`.
    """

    def __init__(self, abi: dict):
        self.constructor = None
        self.fallback = None

        functions = []

        for entry in abi:
            if entry['type'] == 'constructor':
                if self.constructor:
                    raise ValueError()
                self.constructor = Method(entry)
            elif entry['type'] == 'function':
                method = Method(entry)
                functions.append(method)
                setattr(self, method.name, method)
            elif entry['type'] == 'fallback':
                if self.fallback:
                    raise ValueError()
                self.fallback = Method(entry)
            elif entry['type'] == 'event':
                # TODO: support this
                pass
            else:
                raise ValueError()

        self._functions = functions
        self._abi = abi

    def __str__(self):
        all_methods = (
            ([self.constructor] if self.constructor else []) +
            ([self.fallback] if self.fallback else [])
            + self._functions)
        method_list = ["    " + str(method) for method in all_methods]
        return "{\n" + "\n".join(method_list) + "\n}"
