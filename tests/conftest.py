from pathlib import Path

import pytest

from pons import EthereumTesterProvider, CompiledContract


@pytest.fixture
def compiled_contract():
    path = Path(__file__).resolve().parent / 'Test.sol'
    yield CompiledContract.from_file(path)


@pytest.fixture
def test_provider():
    yield EthereumTesterProvider()

