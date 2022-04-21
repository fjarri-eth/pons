from pathlib import Path

import pytest

from .provider import EthereumTesterProvider


@pytest.fixture
def test_provider():
    yield EthereumTesterProvider()
