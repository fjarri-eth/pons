from contextlib import asynccontextmanager
from http import HTTPStatus

import pytest
import trio

from pons import (
    Amount,
    Client,
    HTTPProvider,
    HTTPProviderServer,
    Unreachable,
    _http_provider_server,  # For monkeypatching purposes
)
from pons._client import BadResponseFormat, ProviderError
from pons._provider import (
    HTTPError,
    InvalidResponse,
    Provider,
    ProviderSession,
    RPCError,
    RPCErrorCode,
)


@pytest.fixture
async def test_server(nursery, local_provider):
    handle = HTTPProviderServer(local_provider)
    await nursery.start(handle)
    yield handle
    await handle.shutdown()


@pytest.fixture
async def session(test_server):
    client = Client(test_server.http_provider)
    async with client.session() as session:
        yield session


async def test_single_value_request(session):
    assert await session.net_version() == "1"


async def test_dict_request(session, root_signer, another_signer):
    await session.transfer(root_signer, another_signer.address, Amount.ether(10))


def test_rpc_error():
    error_code = 2

    error = RPCError.from_json({"code": error_code, "message": "error", "data": "additional data"})
    assert error.code == error_code
    assert error.data == "additional data"
    assert error.to_json() == {"code": error_code, "message": "error", "data": "additional data"}

    error = RPCError.from_json({"code": error_code, "message": "error"})
    assert error.data is None
    assert error.to_json() == {"code": error_code, "message": "error"}

    error = RPCError.from_json({"code": str(error_code), "message": "error"})
    assert error.code == error_code

    error = RPCError.invalid_request()
    assert error.code == RPCErrorCode.INVALID_REQUEST.value

    error = RPCError.method_not_found("abc")
    assert error.code == RPCErrorCode.METHOD_NOT_FOUND.value

    with pytest.raises(
        InvalidResponse, match=r"Error data must be a string or None, got <class 'int'> \(1\)"
    ):
        RPCError.from_json({"data": 1, "code": 2, "message": "error"})

    with pytest.raises(
        InvalidResponse,
        match=(
            r"Error code must be an integer \(possibly string-encoded\), "
            r"got <class 'float'> \(1\.0\)"
        ),
    ):
        RPCError.from_json({"code": 1.0, "message": "error"})

    with pytest.raises(
        InvalidResponse, match=r"Error message must be a string, got <class 'int'> \(1\)"
    ):
        RPCError.from_json({"code": 2, "message": 1})


async def test_dict_request_introspection(session, root_signer, another_signer):
    # This test covers the __contains__ method of ResponseDict.
    # It is invoked when the error response is checked for the "data" field,
    # so we trigger an intentionally bad transaction.
    # A little roundabout, is there a better way?
    with pytest.raises(
        ProviderError,
        match="Sender does not have enough balance to cover transaction value and gas",
    ):
        await session.estimate_transfer(
            root_signer.address, another_signer.address, Amount.ether(1000)
        )


async def test_unexpected_response_type(
    local_provider, session, monkeypatch, root_signer, another_signer
):
    tx_hash = await session.broadcast_transfer(
        root_signer, another_signer.address, Amount.ether(10)
    )

    monkeypatch.setattr(local_provider, "rpc", lambda _method, *_args: "something")

    with pytest.raises(BadResponseFormat, match="Expected a dictionary as a response, got str"):
        await session.eth_get_transaction_receipt(tx_hash)


async def test_missing_field(local_provider, session, monkeypatch, root_signer, another_signer):
    orig_rpc = local_provider.rpc

    def mock_rpc(method, *args):
        result = orig_rpc(method, *args)
        if method == "eth_getTransactionReceipt":
            del result["status"]
        return result

    tx_hash = await session.broadcast_transfer(
        root_signer, another_signer.address, Amount.ether(10)
    )

    monkeypatch.setattr(local_provider, "rpc", mock_rpc)

    with pytest.raises(
        BadResponseFormat, match="Expected field `status` is missing from the result"
    ):
        await session.eth_get_transaction_receipt(tx_hash)


async def test_none_instead_of_dict(
    local_provider, session, monkeypatch, root_signer, another_signer
):
    tx_hash = await session.broadcast_transfer(
        root_signer, another_signer.address, Amount.ether(10)
    )

    # Check that a None can be returned in a call that expects a `dict`
    # (the interpretation of such an event is up to the client).
    # `eth_getTransactionReceipt` can return a None normally (if there's no receipt yet),
    # but we force it here, just in case.
    monkeypatch.setattr(local_provider, "rpc", lambda _method, *_args: None)

    assert await session.eth_get_transaction_receipt(tx_hash) is None


async def test_non_json_response(local_provider, session, monkeypatch):
    def faulty_net_version(_method, *_args):
        # A generic exception will generate a 500 status code
        raise Exception("Something unexpected happened")  # noqa: TRY002

    monkeypatch.setattr(local_provider, "rpc", faulty_net_version)

    message = "Expected a JSON response, got HTTP status 500: Something unexpected happened"
    with pytest.raises(BadResponseFormat, match=message):
        await session.net_version()


async def test_no_result_field(session, monkeypatch):
    # Tests the handling of a badly formed success response without the "result" field.

    orig_process_request = _http_provider_server.process_request

    async def faulty_process_request(*args, **kwargs):
        status, response = await orig_process_request(*args, **kwargs)
        del response["result"]
        return (status, response)

    monkeypatch.setattr(_http_provider_server, "process_request", faulty_process_request)

    with pytest.raises(BadResponseFormat, match="`result` is not present in the response"):
        await session.net_version()


async def test_no_error_field(session, monkeypatch):
    # Tests the handling of a badly formed success response without the "error" field.

    orig_process_request = _http_provider_server.process_request

    async def faulty_process_request(*args, **kwargs):
        status, response = await orig_process_request(*args, **kwargs)
        del response["result"]
        return (HTTPStatus.BAD_REQUEST, response)

    monkeypatch.setattr(_http_provider_server, "process_request", faulty_process_request)

    with pytest.raises(HTTPError, match=r"HTTP status 400: {\"jsonrpc\":\"2.0\",\"id\":0}"):
        await session.net_version()


async def test_result_is_not_a_dict(session, monkeypatch):
    # Tests the handling of a badly formed provider response that is not a dictionary.
    # Unfortunately we can't achieve that by just patching the provider, have to patch the server

    async def faulty_process_request(*_args, **_kwargs):
        return (HTTPStatus.OK, 1)

    monkeypatch.setattr(_http_provider_server, "process_request", faulty_process_request)

    with pytest.raises(BadResponseFormat, match="RPC response must be a dictionary, got: 1"):
        await session.net_version()


async def test_unreachable_provider():
    bad_provider = HTTPProvider("https://127.0.0.1:8889")
    client = Client(bad_provider)
    async with client.session() as session:
        with trio.fail_after(1):  # Shouldn't be necessary, but just so that the test doesn't hang
            with pytest.raises(
                Unreachable, match=r"all attempts to connect to 127\.0\.0\.1:8889 failed"
            ):
                await session.net_version()


async def test_default_implementations():
    class MockProvider(Provider):
        @asynccontextmanager
        async def session(self):
            yield MockSession()

    class MockSession(ProviderSession):
        async def rpc(self, method, *_args):
            return method

    provider = MockProvider()
    async with provider.session() as session:
        result = await session.rpc_and_pin("1")
        assert result == ("1", ())

        result = await session.rpc_at_pin((), "2")
        assert result == "2"

        with pytest.raises(ValueError, match=r"Unexpected provider path: \(1,\)"):
            await session.rpc_at_pin((1,), "3")


def test_unknown_rpc_error_code():
    assert RPCErrorCode.from_int(-12345) == RPCErrorCode.UNKNOWN_REASON
