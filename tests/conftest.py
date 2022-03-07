from pathlib import Path

import pytest

from .compile import compile_contract
from .provider import EthereumTesterProvider


@pytest.fixture
def compiled_contract():
    path = Path(__file__).resolve().parent / 'Test.sol'
    yield compile_contract(path)


@pytest.fixture
def test_provider():
    yield EthereumTesterProvider()
