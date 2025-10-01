import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import Enum

import pytest
from ethereum_rpc import ErrorCode, RPCError

from pons import CycleFallback, FallbackProvider, PriorityFallback, Unreachable
from pons._fallback_provider import PriorityFallbackStrategy
from pons._provider import RPC_JSON, InvalidResponse, Provider, ProviderSession


def random_request() -> str:
    return os.urandom(2).hex()


class ProviderState(Enum):
    NORMAL = 1
    UNREACHABLE = 2
    BAD_RESPONSE = 3
    RPC_ERROR = 4


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
            raise Unreachable("")
        if self.provider.state == ProviderState.BAD_RESPONSE:
            raise InvalidResponse("")
        if self.provider.state == ProviderState.RPC_ERROR:
            raise RPCError(ErrorCode(-1), "")
        return "success"


async def test_default_fallback() -> None:
    providers = [MockProvider() for i in range(3)]
    provider = FallbackProvider(providers)
    assert isinstance(provider._strategy, PriorityFallbackStrategy)


def test_inconsistent_weights_length() -> None:
    providers = [MockProvider() for i in range(3)]
    msg = r"Length of the weights \(2\) inconsistent with the number of providers \(3\)"
    with pytest.raises(ValueError, match=msg):
        FallbackProvider(providers, CycleFallback([1, 2]))


async def test_cycle_fallback() -> None:
    strategy = CycleFallback()
    providers = [MockProvider() for i in range(3)]
    provider = FallbackProvider(providers, strategy)

    requests = [str(x) for x in range(10)]
    async with provider.session() as session:
        for request in requests:
            await session.rpc(request)

    assert providers[0].requests == ["0", "3", "6", "9"]
    assert providers[1].requests == ["1", "4", "7"]
    assert providers[2].requests == ["2", "5", "8"]


async def test_cycle_fallback_custom_weights() -> None:
    strategy = CycleFallback([3, 1, 2])
    providers = [MockProvider() for i in range(3)]
    provider = FallbackProvider(providers, strategy)

    requests = [str(x) for x in range(10)]
    async with provider.session() as session:
        for request in requests:
            await session.rpc(request)

    assert providers[0].requests == ["0", "1", "2", "6", "7", "8"]
    assert providers[1].requests == ["3", "9"]
    assert providers[2].requests == ["4", "5"]


async def test_fallback_on_errors() -> None:
    strategy = PriorityFallback()
    providers = [MockProvider() for i in range(3)]
    provider = FallbackProvider(providers, strategy)

    async with provider.session() as session:
        # All providers working, 0 is queried first.
        request = random_request()
        result = await session.rpc(request)
        assert result == "success"
        assert providers[0].requests[-1] == request

        # 0 is unreachable, 1 is queried next.
        providers[0].set_state(ProviderState.UNREACHABLE)
        request = random_request()
        result = await session.rpc(request)
        assert result == "success"
        assert providers[1].requests[-1] == request

        # 0 returns an RPC error, 1 is unreachable, 2 is queried next.
        providers[0].set_state(ProviderState.RPC_ERROR)
        providers[1].set_state(ProviderState.UNREACHABLE)
        request = random_request()
        result = await session.rpc(request)
        assert result == "success"
        assert providers[2].requests[-1] == request


async def test_raising_errors() -> None:
    strategy = PriorityFallback()
    providers = [MockProvider() for i in range(3)]
    provider = FallbackProvider(providers, strategy)

    async with provider.session() as session:
        # All are unreachable, an Unreachable is raised
        providers[0].set_state(ProviderState.UNREACHABLE)
        providers[1].set_state(ProviderState.UNREACHABLE)
        providers[2].set_state(ProviderState.UNREACHABLE)
        with pytest.raises(Unreachable):
            await session.rpc(random_request())

        # InvalidResponse is raised if present
        providers[0].set_state(ProviderState.UNREACHABLE)
        providers[1].set_state(ProviderState.BAD_RESPONSE)
        providers[2].set_state(ProviderState.UNREACHABLE)
        with pytest.raises(InvalidResponse):
            await session.rpc(random_request())

        # RPCError is raised if present
        providers[0].set_state(ProviderState.UNREACHABLE)
        providers[1].set_state(ProviderState.BAD_RESPONSE)
        providers[2].set_state(ProviderState.RPC_ERROR)
        with pytest.raises(RPCError):
            await session.rpc(random_request())


async def test_nested_providers() -> None:
    providers = [MockProvider() for i in range(4)]
    subprovider1 = FallbackProvider([providers[0], providers[1]], PriorityFallback())
    subprovider2 = FallbackProvider(
        [providers[2], providers[3]], PriorityFallback(), same_provider=True
    )
    provider = FallbackProvider([subprovider1, subprovider2], PriorityFallback())

    async with provider.session() as session:
        # All providers operational, provider 0 is pinned
        request = random_request()
        _result, path = await session.rpc_and_pin(request)
        assert path == (0, 0)
        assert providers[0].requests[-1] == request

        # Provider 0 offline, so trying to rpc it specifically results in an error
        providers[0].set_state(ProviderState.UNREACHABLE)
        with pytest.raises(Unreachable):
            await session.rpc_at_pin(path, request)

        # Provider 0 is still offline, pinning results in using provider 1
        request = random_request()
        _result, path = await session.rpc_and_pin(request)
        assert path == (0, 1)
        assert providers[1].requests[-1] == request

        request = random_request()
        _result = await session.rpc_at_pin(path, request)
        assert providers[1].requests[-1] == request

        # All but provider 2 are offline
        request = random_request()
        providers[0].set_state(ProviderState.UNREACHABLE)
        providers[1].set_state(ProviderState.UNREACHABLE)
        providers[3].set_state(ProviderState.UNREACHABLE)
        _result, path = await session.rpc_and_pin(request)
        assert path == (1, 0)
        assert providers[2].requests[-1] == request

        # Since provider 2 and 3 are marked as "same provider",
        # provider 3 can be used instead of the pinned provider 2
        request = random_request()
        providers[3].set_state(ProviderState.NORMAL)
        providers[2].set_state(ProviderState.UNREACHABLE)
        await session.rpc_at_pin(path, request)
        assert providers[3].requests[-1] == request


async def test_invalid_path() -> None:
    providers = [MockProvider() for i in range(4)]
    subprovider1 = FallbackProvider([providers[0], providers[1]], PriorityFallback())
    subprovider2 = FallbackProvider(
        [providers[2], providers[3]], PriorityFallback(), same_provider=True
    )
    provider = FallbackProvider([subprovider1, subprovider2], PriorityFallback())
    async with provider.session() as session:
        with pytest.raises(ValueError, match=r"Invalid provider path: \(2, 0\)"):
            await session.rpc_at_pin((2, 0), random_request())
