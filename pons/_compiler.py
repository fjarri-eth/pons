from enum import Enum
from pathlib import Path
from typing import Dict, Mapping, Optional, Union

import solcx

from ._contract import CompiledContract


class EVMVersion(Enum):
    """
    Supported EVM versions.
    Some may not be available depending on the compiler version.
    """

    HOMESTEAD = "homestead"
    TANGERINE_WHISTLE = "tangerineWhistle"
    SPURIOUS_DRAGON = "spuriousDragon"
    BYZANTIUM = "byzantium"
    CONSTANTINOPLE = "constantinople"
    PETERSBURG = "petersburg"
    ISTANBUL = "istanbul"
    BERLIN = "berlin"
    LONDON = "london"
    PARIS = "paris"
    SHANGHAI = "shanghai"


def compile_contract_file(
    path: Union[str, Path],
    *,
    import_remappings: Mapping[str, Union[str, Path]] = {},
    optimize: bool = False,
    evm_version: Optional[EVMVersion] = None,
) -> Dict[str, CompiledContract]:
    """
    Compiles the Solidity file at the given ``path`` and returns a dictionary of compiled contracts
    keyed by the contract name.

    Some ``evm_version`` values may not be available depending on the compiler version.
    If ``evm_version`` is not given, the compiler default is used.
    """
    path = Path(path).resolve()

    compiled = solcx.compile_files(
        [path],
        output_values=["abi", "bin"],
        evm_version=evm_version.value if evm_version else None,
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

        # When `.sol` files are imported, all contracts are added to the flat namespace.
        # So all the contract names are guaranteed to be different,
        # otherwise the compilation fails.
        results[contract_name] = contract

    return results
