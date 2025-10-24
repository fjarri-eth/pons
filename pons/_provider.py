from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass

from ethereum_rpc import RPCError

RPC_JSON = None | bool | int | float | str | Sequence["RPC_JSON"] | Mapping[str, "RPC_JSON"]
"""RPC requests and responses serializable to JSON."""


class InvalidResponse(Exception):
    """Raised when the remote server's response is not of an expected format."""


class Unreachable(Exception):
    """Raised when there is a problem connecting to the provider."""


class ProtocolError(ABC, Exception):
    """
    A protocol-specific error, indicating that the provider returned an error status
    with no additional information allowing to categorize the error further.

    See the provider-specifc derived class for this exception for more details.
    """


@dataclass
class ProviderError(Exception):
    """Describes an error on the provider's side."""

    error: RPCError | Unreachable | InvalidResponse | ProtocolError
    """The specific error."""

    def __str__(self) -> str:
        return f"Provider error: {self.error}"


class ProviderPath:
    """Identifies a pinned provider."""

    def __init__(self, path: Iterable[str]):
        self._path = tuple(path)

    def group(self, id_: str) -> "ProviderPath":
        """Prepends ``id_`` to the path."""
        return ProviderPath((id_, *self._path))

    def ungroup(self) -> "tuple[str, ProviderPath]":
        """Returns the top-level id and the subpath."""
        return (self._path[0], ProviderPath(self._path[1:]))

    @classmethod
    def empty(cls) -> "ProviderPath":
        """Returns an empty path."""
        return cls(())

    def is_empty(self) -> bool:
        """Returns ``True`` if the path is empty."""
        return not bool(self._path)

    def __str__(self) -> str:
        return "/".join(self._path)

    def __repr__(self) -> str:
        return f"ProviderPath({self._path!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ProviderPath) and self._path == other._path

    def __hash__(self) -> int:
        return hash((ProviderPath, self._path))


class Provider(ABC):
    """The base class for JSON RPC providers."""

    @abstractmethod
    @asynccontextmanager
    async def session(self) -> AsyncIterator["ProviderSession"]:
        """
        Opens a session to the provider
        (allowing the backend to perform multiple operations faster).
        """
        # mypy does not work with abstract generators correctly.
        # See https://github.com/python/mypy/issues/5070
        yield  # type: ignore[misc]


class ProviderSession(ABC):
    """
    The base class for provider sessions.

    The methods of this class may raise :py:class:`ProviderError`
    indicating a problem on the provider's side.
    """

    @abstractmethod
    async def rpc(self, method: str, *args: RPC_JSON) -> RPC_JSON:
        """Calls the given RPC method with the already json-ified arguments."""
        ...

    async def rpc_and_pin(self, method: str, *args: RPC_JSON) -> tuple[RPC_JSON, ProviderPath]:
        """
        Calls the given RPC method and returns the path to the provider it succeded on.
        This method will be typically overriden by multi-provider implementations.
        """
        return await self.rpc(method, *args), ProviderPath.empty()

    async def rpc_at_pin(self, path: ProviderPath, method: str, *args: RPC_JSON) -> RPC_JSON:
        """
        Calls the given RPC method at the provider by the given path
        (obtained previously from ``rpc_and_pin()``).
        This method will be typically overriden by multi-provider implementations.
        """
        if not path.is_empty():
            raise ValueError(f"Expected an empty provider path, got: `{path}`")
        return await self.rpc(method, *args)
