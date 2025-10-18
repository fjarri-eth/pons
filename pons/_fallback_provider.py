import threading
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable, Mapping
from collections.abc import Set as AbstractSet
from contextlib import AsyncExitStack, asynccontextmanager

from ._provider import (
    RPC_JSON,
    Provider,
    ProviderError,
    ProviderPath,
    ProviderSession,
)


class FallbackStrategy(ABC):
    """An abstract class defining a fallback strategy for multiple providers."""

    @abstractmethod
    def get_provider_order(self) -> list[str]:
        """
        Returns the suggested order of providers to query, based on the accumulated data.
        This method is called once on every high-level request to the provider.
        """


class FallbackStrategyFactory(ABC):
    """
    An abstract class defining a fallback strategy factory for multiple providers.
    This will be called in ``FallbackProvider`` to create an actual strategy object
    (which may be mutated).
    """

    @abstractmethod
    def make_strategy(self, provider_ids: AbstractSet[str]) -> FallbackStrategy:
        """Returns a strategy object."""


class CycleFallbackStrategy(FallbackStrategy):
    def __init__(self, weights: dict[str, int]):
        self._weights = weights
        self._provider_ids = list(weights.keys())
        self._counter = 0

    def get_provider_order(self) -> list[str]:
        if self._counter == self._weights[self._provider_ids[0]]:
            self._counter = 0
            self._provider_ids = [*self._provider_ids[1:], self._provider_ids[0]]

        self._counter += 1
        return self._provider_ids


class CycleFallback(FallbackStrategyFactory):
    """
    Creates a strategy where the providers are cycled such that the number of times
    a given provider is first in the priority list is equal
    to the corresponding entry in ``weights``
    (the length of which should match the number of providers).
    If ``weights`` is not given, a list of ``1`` will be used.
    """

    def __init__(self, weights: None | Iterable[int] = None):
        self._weights: None | list[int]
        if weights:
            self._weights = list(weights)
        else:
            self._weights = None

    def make_strategy(self, provider_ids: AbstractSet[str]) -> CycleFallbackStrategy:
        num_providers = len(provider_ids)
        weights = self._weights or [1] * num_providers

        if len(weights) != num_providers:
            raise ValueError(
                f"Length of the weights ({len(weights)}) "
                f"inconsistent with the number of providers ({num_providers})"
            )

        return CycleFallbackStrategy(dict(zip(provider_ids, weights, strict=True)))


class PriorityFallbackStrategy(FallbackStrategy):
    """
    Creates a strategy where the providers are queried in the order
    they were given to ``FallbackProvider``, until a successful response is received.
    """

    def __init__(self, provider_ids: AbstractSet[str]):
        self._provider_ids = list(provider_ids)

    def get_provider_order(self) -> list[str]:
        return self._provider_ids


class PriorityFallback(FallbackStrategyFactory):
    def make_strategy(self, provider_ids: AbstractSet[str]) -> PriorityFallbackStrategy:
        return PriorityFallbackStrategy(provider_ids)


class FallbackProvider(Provider):
    """
    A provider that encompasses several providers and for every request
    tries every one of them until the request is successful.
    The order is chosen according to the given strategy.

    If ``same_provider`` is ``True``, the given providers are treated as endpoints
    pointing to the same physical provider, for the purpose of stateful requests
    (e.g. filter creation).

    If ``strategy`` is ``None``, an instance of :py:class:`PriorityFallback` is used.

    If a request attempt results in an error for which ``use_fallback`` returns ``True``,
    the next provider based on the chosen strategy will be selected.
    Otherwise (or if it is the last provider), the error is raised normally.
    """

    def __init__(
        self,
        providers: Mapping[str, Provider],
        strategy: FallbackStrategyFactory | None = None,
        *,
        same_provider: bool = False,
    ):
        self._providers = dict(providers)
        strategy_ = strategy if strategy is not None else PriorityFallback()
        self._strategy = strategy_.make_strategy(self._providers.keys())
        self._same_provider = same_provider
        self._errors: dict[str, ProviderError] = {}
        self._lock = threading.Lock()

    @asynccontextmanager
    async def session(self) -> AsyncIterator["ProviderSession"]:
        async with AsyncExitStack() as stack:
            sessions = {
                provider_id: await stack.enter_async_context(provider.session())
                for provider_id, provider in self._providers.items()
            }
            yield FallbackProviderSession(
                self,
                sessions,
                self._strategy,
                same_provider=self._same_provider,
            )

    def errors(self) -> list[tuple[ProviderPath, ProviderError]]:
        """
        Returns the list of recorded errors for sub-providers.

        Only the most recent error for every sub-provider is recorded.
        Querying this method clears the recorded errors.
        """
        errors = []

        with self._lock:
            for provider_id, error in self._errors.items():
                errors.append((ProviderPath([provider_id]), error))
            self._errors = {}

        for provider_id, provider in self._providers.items():
            if isinstance(provider, FallbackProvider):
                sub_errors = provider.errors()
                for sub_path, error in sub_errors:
                    errors.append((sub_path.group(provider_id), error))

        return errors

    def record_error(self, provider_id: str, exc: ProviderError) -> None:
        with self._lock:
            self._errors[provider_id] = exc


class FallbackProviderSession(ProviderSession):
    def __init__(
        self,
        provider: FallbackProvider,
        sessions: dict[str, ProviderSession],
        strategy: FallbackStrategy,
        *,
        same_provider: bool,
    ):
        self._provider = provider
        self._sessions = sessions
        self._strategy = strategy
        self._same_provider = same_provider

    async def rpc_and_pin(self, method: str, *args: RPC_JSON) -> tuple[RPC_JSON, ProviderPath]:
        provider_ids = self._strategy.get_provider_order()

        for i, provider_id in enumerate(provider_ids):
            session = self._sessions[provider_id]
            try:
                result, sub_path = await session.rpc_and_pin(method, *args)
            except ProviderError as exc:
                if not isinstance(session, FallbackProviderSession):
                    self._provider.record_error(provider_id, exc)

                if i < len(provider_ids) - 1:
                    continue

                raise

            break

        else:  # pragma: no cover
            # This branch will never be reached, because the loop will either return,
            # or raise an exception.
            raise NotImplementedError

        return result, sub_path.group(provider_id)

    async def rpc(self, method: str, *args: RPC_JSON) -> RPC_JSON:
        result, _path = await self.rpc_and_pin(method, *args)
        return result

    async def rpc_at_pin(self, path: ProviderPath, method: str, *args: RPC_JSON) -> RPC_JSON:
        if self._same_provider:
            return await self.rpc(method, *args)
        if path.is_empty():
            raise ValueError("Expected a non-empty provider path")
        provider_id, sub_path = path.ungroup()
        if provider_id not in self._sessions:
            raise ValueError(f"Provider id `{provider_id}` not found")
        return await self._sessions[provider_id].rpc_at_pin(sub_path, method, *args)
