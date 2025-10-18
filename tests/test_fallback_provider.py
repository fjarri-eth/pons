import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import Enum
from http import HTTPStatus

import pytest
from ethereum_rpc import ErrorCode, RPCError

from pons import (
    CycleFallback,
    FallbackProvider,
    HTTPError,
    InvalidResponse,
    PriorityFallback,
    ProtocolError,
    Provider,
    ProviderError,
    ProviderPath,
    Unreachable,
)
from pons._fallback_provider import PriorityFallbackStrategy
from pons._provider import RPC_JSON, ProviderSession


def random_request() -> str:
    return os.urandom(2).hex()


class ProviderState(Enum):
    NORMAL = 1
    UNREACHABLE = 2
    BAD_RESPONSE = 3
    RPC_ERROR = 4
    PROTOCOL_ERROR = 5


class MockProvider(Provider):
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.state = ProviderState.NORMAL

    def set_state(self, state: ProviderState) -> None:
        self.state = state

    @asynccontextmanager
    async def session(self) -> AsyncIterator["ProviderSession"]:
        yield MockSession(self)


class MockSession(ProviderSession):
    def __init__(self, provider: MockProvider):
        self.provider = provider

    async def rpc(self, method: str, *_args: RPC_JSON) -> RPC_JSON:
        self.provider.requests.append(method)
        if self.provider.state == ProviderState.UNREACHABLE:
            raise ProviderError(Unreachable(""))
        if self.provider.state == ProviderState.BAD_RESPONSE:
            raise ProviderError(InvalidResponse(""))
        if self.provider.state == ProviderState.RPC_ERROR:
            raise ProviderError(RPCError(ErrorCode(-1), ""))
        if self.provider.state == ProviderState.PROTOCOL_ERROR:
            raise ProviderError(HTTPError(HTTPStatus(500), ""))

        return "success"


async def test_default_fallback() -> None:
    providers = {str(i): MockProvider() for i in range(3)}
    provider = FallbackProvider(providers)
    assert isinstance(provider._strategy, PriorityFallbackStrategy)


def test_inconsistent_weights_length() -> None:
    providers = {str(i): MockProvider() for i in range(3)}
    msg = r"Length of the weights \(2\) inconsistent with the number of providers \(3\)"
    with pytest.raises(ValueError, match=msg):
        FallbackProvider(providers, CycleFallback([1, 2]))


async def test_cycle_fallback() -> None:
    strategy = CycleFallback()
    providers = {str(i): MockProvider() for i in range(3)}
    provider = FallbackProvider(providers, strategy)

    requests = [str(x) for x in range(10)]
    async with provider.session() as session:
        for request in requests:
            await session.rpc(request)

    assert providers["0"].requests == ["0", "3", "6", "9"]
    assert providers["1"].requests == ["1", "4", "7"]
    assert providers["2"].requests == ["2", "5", "8"]


async def test_cycle_fallback_custom_weights() -> None:
    strategy = CycleFallback([3, 1, 2])
    providers = {str(i): MockProvider() for i in range(3)}
    provider = FallbackProvider(providers, strategy)

    requests = [str(x) for x in range(10)]
    async with provider.session() as session:
        for request in requests:
            await session.rpc(request)

    assert providers["0"].requests == ["0", "1", "2", "6", "7", "8"]
    assert providers["1"].requests == ["3", "9"]
    assert providers["2"].requests == ["4", "5"]


async def test_fallback_on_errors() -> None:
    strategy = PriorityFallback()
    providers = {str(i): MockProvider() for i in range(3)}
    provider = FallbackProvider(providers, strategy)

    async with provider.session() as session:
        # All providers working, 0 is queried first.
        request = random_request()
        result = await session.rpc(request)
        assert result == "success"
        assert providers["0"].requests[-1] == request

        # 0 is unreachable, 1 is queried next.
        providers["0"].set_state(ProviderState.UNREACHABLE)
        request = random_request()
        result = await session.rpc(request)
        assert result == "success"
        assert providers["1"].requests[-1] == request

        # 0 returns a protocol error, 1 is unreachable, 2 is queried next.
        providers["0"].set_state(ProviderState.PROTOCOL_ERROR)
        providers["1"].set_state(ProviderState.UNREACHABLE)
        request = random_request()
        result = await session.rpc(request)
        assert result == "success"
        assert providers["2"].requests[-1] == request


async def test_raising_errors() -> None:
    strategy = PriorityFallback()
    providers = {str(i): MockProvider() for i in range(3)}
    provider = FallbackProvider(providers, strategy)

    async with provider.session() as session:
        providers["0"].set_state(ProviderState.UNREACHABLE)
        providers["1"].set_state(ProviderState.UNREACHABLE)
        providers["2"].set_state(ProviderState.UNREACHABLE)
        with pytest.raises(ProviderError) as excinfo:
            await session.rpc(random_request())
        assert isinstance(excinfo.value.error, Unreachable)

        providers["0"].set_state(ProviderState.UNREACHABLE)
        providers["1"].set_state(ProviderState.BAD_RESPONSE)
        providers["2"].set_state(ProviderState.UNREACHABLE)
        with pytest.raises(ProviderError) as excinfo:
            await session.rpc(random_request())
        assert isinstance(excinfo.value.error, Unreachable)

        providers["0"].set_state(ProviderState.UNREACHABLE)
        providers["1"].set_state(ProviderState.RPC_ERROR)
        providers["2"].set_state(ProviderState.BAD_RESPONSE)
        with pytest.raises(ProviderError) as excinfo:
            await session.rpc(random_request())
        assert isinstance(excinfo.value.error, InvalidResponse)


async def test_nested_providers() -> None:
    providers = {str(i): MockProvider() for i in range(4)}
    subprovider0 = FallbackProvider({"0": providers["0"], "1": providers["1"]}, PriorityFallback())
    subprovider1 = FallbackProvider(
        {"2": providers["2"], "3": providers["3"]}, PriorityFallback(), same_provider=True
    )
    provider = FallbackProvider({"s0": subprovider0, "s1": subprovider1}, PriorityFallback())

    async with provider.session() as session:
        # All providers operational, provider 0 is pinned
        request = random_request()
        _result, path = await session.rpc_and_pin(request)
        assert str(path) == "s0/0"
        assert providers["0"].requests[-1] == request

        # Provider 0 offline, so trying to rpc it specifically results in an error
        providers["0"].set_state(ProviderState.UNREACHABLE)
        with pytest.raises(ProviderError) as excinfo:
            await session.rpc_at_pin(path, request)
        assert isinstance(excinfo.value.error, Unreachable)

        # Provider 0 is still offline, pinning results in using provider 1
        request = random_request()
        _result, path = await session.rpc_and_pin(request)
        assert str(path) == "s0/1"
        assert providers["1"].requests[-1] == request

        request = random_request()
        _result = await session.rpc_at_pin(path, request)
        assert providers["1"].requests[-1] == request

        # All but provider 2 are offline
        request = random_request()
        providers["0"].set_state(ProviderState.UNREACHABLE)
        providers["1"].set_state(ProviderState.UNREACHABLE)
        providers["3"].set_state(ProviderState.UNREACHABLE)
        _result, path = await session.rpc_and_pin(request)
        assert str(path) == "s1/2"
        assert providers["2"].requests[-1] == request

        # Since provider 2 and 3 are marked as "same provider",
        # provider 3 can be used instead of the pinned provider 2
        request = random_request()
        providers["3"].set_state(ProviderState.NORMAL)
        providers["2"].set_state(ProviderState.UNREACHABLE)
        await session.rpc_at_pin(path, request)
        assert providers["3"].requests[-1] == request


async def test_invalid_path() -> None:
    subprovider0 = FallbackProvider({"0": MockProvider(), "1": MockProvider()}, PriorityFallback())
    subprovider1 = FallbackProvider(
        {"2": MockProvider(), "3": MockProvider()}, PriorityFallback(), same_provider=True
    )
    provider = FallbackProvider({"s0": subprovider0, "s1": subprovider1}, PriorityFallback())
    async with provider.session() as session:
        with pytest.raises(ValueError, match="Provider id `s2` not found"):
            await session.rpc_at_pin(ProviderPath(["s2", "0"]), random_request())

    async with provider.session() as session:
        with pytest.raises(ValueError, match="Expected a non-empty provider path"):
            await session.rpc_at_pin(ProviderPath.empty(), random_request())


def assert_errors(
    errors: list[tuple[ProviderPath, ProviderError]],
    reference: list[tuple[ProviderPath, type[Exception]]],
) -> None:
    # Since exceptions don't implement equality
    for (test_path, exc), (ref_path, exc_type) in zip(errors, reference, strict=True):
        assert test_path == ref_path
        assert isinstance(exc.error, exc_type)


async def test_error_collection() -> None:
    providers = {str(i): MockProvider() for i in range(6)}
    subprovider0 = FallbackProvider({"0": providers["0"], "1": providers["1"]}, PriorityFallback())
    subprovider1 = FallbackProvider(
        {"2": providers["2"], "3": providers["3"]}, PriorityFallback(), same_provider=True
    )
    provider = FallbackProvider(
        {"s0": subprovider0, "s1": subprovider1, "s2": providers["4"], "s3": providers["5"]},
        PriorityFallback(),
    )

    async with provider.session() as session:
        providers["0"].set_state(ProviderState.UNREACHABLE)
        _result, _path = await session.rpc_and_pin(random_request())
        assert_errors(
            provider.errors(),
            [
                (ProviderPath(("s0", "0")), Unreachable),
            ],
        )

        # Now the whole `subprovider1` is unreachable
        providers["1"].set_state(ProviderState.UNREACHABLE)
        providers["2"].set_state(ProviderState.RPC_ERROR)
        _result, _path = await session.rpc_and_pin(random_request())
        assert_errors(
            provider.errors(),
            [
                (ProviderPath(("s0", "0")), Unreachable),
                (ProviderPath(("s0", "1")), Unreachable),
                (ProviderPath(("s1", "2")), RPCError),
            ],
        )

        # This will override the recorded error
        _result, _path = await session.rpc_and_pin(random_request())
        providers["0"].set_state(ProviderState.BAD_RESPONSE)
        providers["1"].set_state(ProviderState.NORMAL)
        _result, _path = await session.rpc_and_pin(random_request())
        assert_errors(
            provider.errors(),
            [
                (ProviderPath(("s0", "0")), InvalidResponse),
                (ProviderPath(("s0", "1")), Unreachable),
                (ProviderPath(("s1", "2")), RPCError),
            ],
        )

        # Test that the top fallback provider errors are included
        providers["1"].set_state(ProviderState.UNREACHABLE)
        providers["3"].set_state(ProviderState.UNREACHABLE)
        providers["4"].set_state(ProviderState.PROTOCOL_ERROR)
        _result, _path = await session.rpc_and_pin(random_request())
        assert_errors(
            provider.errors(),
            [
                (ProviderPath(("s2",)), ProtocolError),
                (ProviderPath(("s0", "0")), InvalidResponse),
                (ProviderPath(("s0", "1")), Unreachable),
                (ProviderPath(("s1", "2")), RPCError),
                (ProviderPath(("s1", "3")), Unreachable),
            ],
        )
