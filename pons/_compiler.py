from collections.abc import Mapping
from enum import Enum
from pathlib import Path

import solcx

from ._contract import CompiledContract


class EVMVersion(Enum):
    """
    Supported EVM versions.
    Some may not be available depending on the compiler version.
    """

    HOMESTEAD = "homestead"
    """Homestead fork, Mar 14, 2016."""

    TANGERINE_WHISTLE = "tangerineWhistle"
    """Tangerine Whistle fork, Oct 18, 2016."""

    SPURIOUS_DRAGON = "spuriousDragon"
    """Spurious Dragon fork, Nov 22, 2016."""

    BYZANTIUM = "byzantium"
    """Byzantium fork, Oct 16, 2017."""

    CONSTANTINOPLE = "constantinople"
    """Constantinople fork, Feb 28, 2019."""

    ISTANBUL = "istanbul"
    """Istanbul fork, Dec 8, 2019."""

    BERLIN = "berlin"
    """Berlin fork, Apr 15, 2021."""

    LONDON = "london"
    """London fork, Aug 5, 2021."""

    PARIS = "paris"
    """Paris fork, Sep 15, 2022."""

    SHANGHAI = "shanghai"
    """Shanghai fork, Apr 12, 2023."""

    CANCUN = "cancun"
    """Cancun fork, Mar 13, 2024."""

    PRAGUE = "prague"
    """Prague fork, May 7, 2025."""


def compile_contract_file(
    path: str | Path,
    *,
    import_remappings: Mapping[str, str | Path] = {},
    optimize: bool = False,
    evm_version: None | EVMVersion = None,
) -> dict[str, CompiledContract]:
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
