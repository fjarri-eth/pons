from pathlib import Path

import solcx

from .contract_abi import ABI


class Contract:

    def __init__(self, abi):
        self.abi = ABI(abi)


class CompiledContract(Contract):

    # TODO: make optional, most people will just use deployed contracts
    @classmethod
    def from_file(cls, path):
        path = Path(path).resolve()

        compiled = solcx.compile_files(
            [path], output_values=["abi", "bin"], evm_version='london')

        # For now this method is only used for testing purposes,
        # so we are assuming there was only one contract in the compiled file.
        assert len(compiled) == 1

        _contract_name, compiled_contract = compiled.popitem()

        return cls(compiled_contract['abi'], bytes.fromhex(compiled_contract['bin']))

    def __init__(self, abi, bytecode):
        super().__init__(abi)
        self.bytecode = bytecode


class DeployedContract:

    def __init__(self, abi, address):
        self.abi = abi
        self.address = address
