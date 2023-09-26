from pathlib import Path
from typing import Dict, Iterable, Mapping, Union

import solcx

from ._contract import CompiledContract


def compile_contract_file(
    path: Union[str, Path],
    import_remappings: Mapping[str, str] = {},
    optimize: bool = False,
    evm_version: str = "london",  # TODO: use an enum
) -> Dict[str, CompiledContract]:
    path = Path(path).resolve()

    compiled = solcx.compile_files(
        [path],
        output_values=["abi", "bin"],
        evm_version=evm_version,
        import_remappings=dict(import_remappings),
        optimize=optimize,
    )

    results = {}
    for identifier, compiled_contract in compiled.items():
        path, contract_name = identifier.split(":")

        contract = CompiledContract.from_compiler_output(
            json_abi=compiled_contract["abi"],
            bytecode=bytes.fromhex(compiled_contract["bin"]),
        )

        # TODO: can we have several identical contract names in the compilation result?
        results[contract_name] = contract

    return results
