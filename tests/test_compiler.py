from pathlib import Path

from pons import EVMVersion, compile_contract_file


def test_multiple_contracts():
    path = Path(__file__).resolve().parent / "TestCompiler.sol"
    contracts = compile_contract_file(path, evm_version=EVMVersion.SHANGHAI, optimize=True)
    assert sorted(contracts) == ["Contract1", "Contract2"]


def test_import_remappings():
    root_path = path = Path(__file__).resolve().parent
    path = root_path / "TestCompilerWithImport.sol"
    contracts = compile_contract_file(
        path, import_remappings={"@to_be_remapped": root_path / "test_compiler_subdir"}
    )
    assert sorted(contracts) == ["Contract1", "Contract2"]
