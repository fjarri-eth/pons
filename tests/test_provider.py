from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Any

import pytest
import trio
from ethereum_rpc import Amount, RPCError
from pytest import MonkeyPatch

from pons import (
    AccountSigner,
    BadResponseFormat,
    Client,
    ClientSession,
    HTTPError,
    HTTPProvider,
    HTTPProviderServer,
    LocalProvider,
    Provider,
    Unreachable,
    _http_provider_server,  # For monkeypatching purposes
)
from pons._provider import RPC_JSON, ProviderPath, ProviderSession


@pytest.fixture
async def test_server(
    nursery: trio.Nursery, local_provider: LocalProvider
) -> AsyncIterator[HTTPProviderServer]:
    handle = HTTPProviderServer(local_provider)
    await nursery.start(handle)
    yield handle
    await handle.shutdown()


@pytest.fixture
async def session(test_server: HTTPProviderServer) -> AsyncIterator[ClientSession]:
    client = Client(test_server.http_provider)
    async with client.session() as session:
        yield session


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


async def test_single_value_request(session: ClientSession) -> None:
    assert await session.net_version() == "1"


async def test_dict_request(
    session: ClientSession, root_signer: AccountSigner, another_signer: AccountSigner
) -> None:
    await session.transfer(root_signer, another_signer.address, Amount.ether(10))


async def test_dict_request_introspection(
    session: ClientSession, root_signer: AccountSigner, another_signer: AccountSigner
) -> None:
    # This test covers the __contains__ method of ResponseDict.
    # It is invoked when the error response is checked for the "data" field,
    # so we trigger an intentionally bad transaction.
    # A little roundabout, is there a better way?
    with pytest.raises(
        RPCError,
        match="Sender does not have enough balance to cover transaction value and gas",
    ):
        await session.estimate_transfer(
            root_signer.address, another_signer.address, Amount.ether(1000)
        )


async def test_unexpected_response_type(
    local_provider: LocalProvider,
    session: ClientSession,
    monkeypatch: MonkeyPatch,
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    tx_hash = await session.broadcast_transfer(
        root_signer, another_signer.address, Amount.ether(10)
    )

    monkeypatch.setattr(local_provider, "rpc", lambda _method, *_args: "something")

    with pytest.raises(BadResponseFormat, match="Cannot structure into"):
        await session.rpc.eth_get_transaction_receipt(tx_hash)


async def test_missing_field(
    local_provider: LocalProvider,
    session: ClientSession,
    monkeypatch: MonkeyPatch,
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    orig_rpc = local_provider.rpc

    def mock_rpc(method: str, *args: Any) -> RPC_JSON:
        result = orig_rpc(method, *args)
        if method == "eth_getTransactionReceipt":
            assert isinstance(result, dict)
            del result["status"]
        return result

    tx_hash = await session.broadcast_transfer(
        root_signer, another_signer.address, Amount.ether(10)
    )

    monkeypatch.setattr(local_provider, "rpc", mock_rpc)

    with pytest.raises(BadResponseFormat, match="status: Missing field"):
        await session.rpc.eth_get_transaction_receipt(tx_hash)


async def test_none_instead_of_dict(
    local_provider: LocalProvider,
    session: ClientSession,
    monkeypatch: MonkeyPatch,
    root_signer: AccountSigner,
    another_signer: AccountSigner,
) -> None:
    tx_hash = await session.broadcast_transfer(
        root_signer, another_signer.address, Amount.ether(10)
    )

    # Check that a None can be returned in a call that expects a `dict`
    # (the interpretation of such an event is up to the client).
    # `eth_getTransactionReceipt` can return a None normally (if there's no receipt yet),
    # but we force it here, just in case.
    monkeypatch.setattr(local_provider, "rpc", lambda _method, *_args: None)

    assert await session.rpc.eth_get_transaction_receipt(tx_hash) is None


async def test_non_json_response(
    local_provider: LocalProvider, session: ClientSession, monkeypatch: MonkeyPatch
) -> None:
    def faulty_net_version(_method: str, *_args: Any) -> RPC_JSON:
        # A generic exception will generate a 500 status code
        raise Exception("Something unexpected happened")  # noqa: TRY002

    monkeypatch.setattr(local_provider, "rpc", faulty_net_version)

    message = "Expected a JSON response, got HTTP status 500: Something unexpected happened"
    with pytest.raises(BadResponseFormat, match=message):
        await session.net_version()


async def test_no_result_field(session: ClientSession, monkeypatch: MonkeyPatch) -> None:
    # Tests the handling of a badly formed success response without the "result" field.

    orig_process_request = _http_provider_server.process_request

    async def faulty_process_request(*args: Any, **kwargs: Any) -> tuple[HTTPStatus, RPC_JSON]:
        status, response = await orig_process_request(*args, **kwargs)
        assert isinstance(response, dict)
        del response["result"]
        return (status, response)

    monkeypatch.setattr(_http_provider_server, "process_request", faulty_process_request)

    with pytest.raises(BadResponseFormat, match="`result` is not present in the response"):
        await session.net_version()


async def test_no_error_field(session: ClientSession, monkeypatch: MonkeyPatch) -> None:
    # Tests the handling of a badly formed error response without the "error" field.

    orig_process_request = _http_provider_server.process_request

    async def faulty_process_request(*args: Any, **kwargs: Any) -> tuple[HTTPStatus, RPC_JSON]:
        _status, response = await orig_process_request(*args, **kwargs)
        assert isinstance(response, dict)
        del response["result"]
        return (HTTPStatus.BAD_REQUEST, response)

    monkeypatch.setattr(_http_provider_server, "process_request", faulty_process_request)

    with pytest.raises(HTTPError, match=r"HTTP status 400: {\"jsonrpc\":\"2.0\",\"id\":0}"):
        await session.net_version()


async def test_malformed_error_field(session: ClientSession, monkeypatch: MonkeyPatch) -> None:
    # Tests the handling of a badly formed error response
    # where the "error" field cannot be parsed as an RPCError.

    orig_process_request = _http_provider_server.process_request

    async def faulty_process_request(*args: Any, **kwargs: Any) -> RPC_JSON:
        _status, response = await orig_process_request(*args, **kwargs)
        assert isinstance(response, dict)
        del response["result"]
        response["error"] = {"something_weird": 1}
        return (HTTPStatus.BAD_REQUEST, response)

    monkeypatch.setattr(_http_provider_server, "process_request", faulty_process_request)

    with pytest.raises(BadResponseFormat, match=r"Failed to parse an error response"):
        await session.net_version()


async def test_result_is_not_a_dict(session: ClientSession, monkeypatch: MonkeyPatch) -> None:
    # Tests the handling of a badly formed provider response that is not a dictionary.
    # Unfortunately we can't achieve that by just patching the provider, have to patch the server

    async def faulty_process_request(*_args: Any, **_kwargs: Any) -> tuple[HTTPStatus, RPC_JSON]:
        return (HTTPStatus.OK, 1)

    monkeypatch.setattr(_http_provider_server, "process_request", faulty_process_request)

    with pytest.raises(BadResponseFormat, match="RPC response must be a dictionary, got: 1"):
        await session.net_version()


async def test_unreachable_provider() -> None:
    bad_provider = HTTPProvider("https://127.0.0.1:8889")
    client = Client(bad_provider)
    async with client.session() as session:
        with trio.fail_after(1):  # Shouldn't be necessary, but just so that the test doesn't hang
            with pytest.raises(
                Unreachable, match=r"all attempts to connect to 127\.0\.0\.1:8889 failed"
            ):
                await session.net_version()


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
