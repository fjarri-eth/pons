from pathlib import Path

import solcx

from pons import ContractABI, CompiledContract


def compile_contract(path) -> CompiledContract:
    path = Path(path).resolve()

    compiled = solcx.compile_files(
        [path], output_values=["abi", "bin"], evm_version='london')

    # For now this method is only used for testing purposes,
    # so we are assuming there was only one contract in the compiled file.
    assert len(compiled) == 1

    _contract_name, compiled_contract = compiled.popitem()
    abi = ContractABI(compiled_contract['abi'])

    return CompiledContract(abi=abi, bytecode=bytes.fromhex(compiled_contract['bin']))
