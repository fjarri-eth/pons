from typing import Dict
from pathlib import Path

import solcx

from pons import CompiledContract


def compile_file(path) -> Dict[str, CompiledContract]:
    path = Path(path).resolve()

    compiled = solcx.compile_files([path], output_values=["abi", "bin"], evm_version="london")

    results = {}
    for identifier, compiled_contract in compiled.items():
        path, contract_name = identifier.split(":")

        contract = CompiledContract.from_compiler_output(
            json_abi=compiled_contract["abi"], bytecode=bytes.fromhex(compiled_contract["bin"])
        )

        results[contract_name] = contract

    return results
