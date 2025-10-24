from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import pytest

from pons import Provider, ProviderError, ProviderPath, Unreachable
from pons._provider import RPC_JSON, ProviderSession

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def test_provider_path() -> None:
    assert ProviderPath.empty().is_empty()
    assert not ProviderPath(["1"]).is_empty()

    assert ProviderPath(["1", "2"]) == ProviderPath(["1", "2"])
    assert ProviderPath(["1", "2"]) != ProviderPath(["1", "3"])

    assert hash(ProviderPath(["1", "2"])) == hash(ProviderPath(["1", "2"]))
    assert hash(ProviderPath(["1", "2"])) != hash(ProviderPath(["1", "3"]))

    assert str(ProviderPath(["1", "2"])) == "1/2"
    assert repr(ProviderPath(["1", "2"])) == "ProviderPath(('1', '2'))"

    assert ProviderPath(["1"]).group("2") == ProviderPath(["2", "1"])
    assert ProviderPath(["1", "2"]).ungroup() == ("1", ProviderPath(["2"]))


def test_provider_error() -> None:
    error = ProviderError(error=Unreachable("the server is unreachable"))
    assert str(error) == "Provider error: the server is unreachable"


async def test_default_implementations() -> None:
    class MockProvider(Provider):
        @asynccontextmanager
        async def session(self) -> "AsyncIterator[MockSession]":
            yield MockSession()

    class MockSession(ProviderSession):
        async def rpc(self, method: str, *_args: RPC_JSON) -> RPC_JSON:
            return method

    provider = MockProvider()
    async with provider.session() as session:
        result1 = await session.rpc_and_pin("1")
        assert result1 == ("1", ProviderPath.empty())

        result2 = await session.rpc_at_pin(ProviderPath.empty(), "2")
        assert result2 == "2"

        with pytest.raises(ValueError, match=r"Expected an empty provider path, got: `1`"):
            await session.rpc_at_pin(ProviderPath(["1"]), "3")
