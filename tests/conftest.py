from pathlib import Path

import pytest

from .compile import compile_file
from .provider import EthereumTesterProvider


@pytest.fixture
def compiled_contracts():
    path = Path(__file__).resolve().parent / 'Test.sol'
    yield compile_file(path)


@pytest.fixture
def test_provider():
    yield EthereumTesterProvider()
