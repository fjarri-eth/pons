# TODO (#60): expand the tests so that this file covered 100% of the respective submodule,
# and don't use high-level API.

import pytest

from pons import RPCError, RPCErrorCode, ServerHandle


@pytest.fixture
async def test_server(nursery, test_provider):
    handle = ServerHandle(test_provider)
    await nursery.start(handle)
    yield handle
    await handle.shutdown()


@pytest.fixture
async def provider_session(test_server):
    async with test_server.http_provider.session() as session:
        yield session


async def test_invalid_method(provider_session):
    with pytest.raises(RPCError) as excinfo:
        await provider_session.rpc(["method1", "method2"], 1, 2, 3)
    assert excinfo.value.code == RPCErrorCode.INVALID_REQUEST.value


async def test_invalid_parameters(provider_session, monkeypatch):
    # There is no public way to do that, have to use the internals
    monkeypatch.setattr(
        provider_session,
        "_prepare_request",
        lambda method, *args: {"jsonrpc": "2.0", "method": method, "params": args[0], "id": 0},
    )

    # Invalid parameters format (not a list)
    with pytest.raises(RPCError) as excinfo:
        await provider_session.rpc("method1", 1, 2, 3)
    assert excinfo.value.code == RPCErrorCode.INVALID_REQUEST.value
