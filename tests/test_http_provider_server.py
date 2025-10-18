from collections.abc import AsyncIterator
from typing import Any

import pytest
import trio
from ethereum_rpc import RPCError, RPCErrorCode

from pons import HTTPProviderServer, LocalProvider, ProviderError
from pons._provider import RPC_JSON, ProviderSession


@pytest.fixture
async def server(
    nursery: trio.Nursery, local_provider: LocalProvider
) -> AsyncIterator[HTTPProviderServer]:
    handle = HTTPProviderServer(local_provider)
    await nursery.start(handle)
    yield handle
    await handle.shutdown()


@pytest.fixture
async def provider_session(server: HTTPProviderServer) -> AsyncIterator[ProviderSession]:
    async with server.http_provider.session() as session:
        yield session


async def test_happy_path(provider_session: ProviderSession) -> None:
    result = await provider_session.rpc("eth_chainId")
    assert result == "0x1"


async def test_invalid_method(provider_session: ProviderSession) -> None:
    with pytest.raises(ProviderError) as excinfo:
        await provider_session.rpc(["method1", "method2"], 1, 2, 3)  # type: ignore[arg-type]
    assert isinstance(excinfo.value.error, RPCError)
    assert excinfo.value.error.parsed_code == RPCErrorCode.INVALID_REQUEST


async def test_invalid_parameters(
    provider_session: ProviderSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # There is no public way to do that, have to use the internals
    monkeypatch.setattr(
        provider_session,
        "_prepare_request",
        lambda method, *args: {"jsonrpc": "2.0", "method": method, "params": args[0], "id": 0},
    )

    # Invalid parameters format (not a list)
    with pytest.raises(ProviderError) as excinfo:
        await provider_session.rpc("method1", 1, 2, 3)
    assert isinstance(excinfo.value.error, RPCError)
    assert excinfo.value.error.parsed_code == RPCErrorCode.INVALID_REQUEST


async def test_internal_error(
    provider_session: ProviderSession,
    local_provider: LocalProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mock_rpc(*_args: Any) -> RPC_JSON:
        raise RuntimeError("foo")

    monkeypatch.setattr(local_provider, "rpc", mock_rpc)
    with pytest.raises(
        ProviderError, match="Provider error: Expected a JSON response, got HTTP status 500: foo"
    ):
        await provider_session.rpc("eth_chainId")
