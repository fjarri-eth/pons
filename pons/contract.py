import solcx

from .contract_abi import ABI


class Contract:

    def __init__(self, abi):
        self.abi = ABI(abi)


class CompiledContract(Contract):

    # TODO: make optional, most people will just use deployed contracts
    @classmethod
    def from_file(cls, path):
        with open(path) as f:
            contract_source = f.read()

        compiled = solcx.compile_source(
            contract_source, output_values=["abi", "bin"], evm_version='london')
        compiled = compiled['<stdin>:Test']

        return cls(compiled['abi'], compiled['bin'])

    def __init__(self, abi, bytecode):
        super().__init__(abi)
        self.bytecode = bytecode


class DeployedContract:

    def __init__(self, abi, address):
        self.abi = abi
        self.address = address
