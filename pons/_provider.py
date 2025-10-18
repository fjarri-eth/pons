from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http import HTTPStatus
from json import JSONDecodeError
from typing import cast

import httpx
from compages import StructuringError
from ethereum_rpc import RPCError, structure

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


class HTTPError(ProtocolError):
    """
    Raised when the provider returns a response with a status code other than 200,
    and no ``"error"`` field in the associated JSON data.
    """

    status: HTTPStatus
    """The HTTP status of the response."""

    message: str
    """The response body."""

    def __init__(self, status_code: int, message: str):
        try:
            status = HTTPStatus(status_code)
        except ValueError:  # pragma: no cover
            # How to handle it better? Ideally, `httpx` should have returned a parsed status
            # in the first place, but, alas, it just gives us an integer.
            status = HTTPStatus.INTERNAL_SERVER_ERROR

        self.status = status
        self.message = message

    def __str__(self) -> str:
        return f"HTTP status {self.status}: {self.message}"


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


class HTTPProvider(Provider):
    """A provider for RPC via HTTP(S)."""

    def __init__(self, url: str):
        self._url = url

    @asynccontextmanager
    async def session(self) -> AsyncIterator["HTTPSession"]:
        async with httpx.AsyncClient() as client:
            yield HTTPSession(self._url, client)


class HTTPSession(ProviderSession):
    def __init__(self, url: str, http_client: httpx.AsyncClient):
        self._url = url
        self._client = http_client

    def _prepare_request(self, method: str, *args: RPC_JSON) -> RPC_JSON:
        return {"jsonrpc": "2.0", "method": method, "params": args, "id": 0}

    async def rpc(self, method: str, *args: RPC_JSON) -> RPC_JSON:
        json = self._prepare_request(method, *args)
        try:
            response = await self._client.post(self._url, json=json)
        except httpx.ConnectError as exc:
            raise ProviderError(Unreachable(str(exc))) from exc

        status = response.status_code

        try:
            response_json = response.json()
        except JSONDecodeError as exc:
            content = response.content.decode()
            raise ProviderError(
                InvalidResponse(f"Expected a JSON response, got HTTP status {status}: {content}")
            ) from exc

        if not isinstance(response_json, Mapping):
            raise ProviderError(
                InvalidResponse(f"RPC response must be a dictionary, got: {response_json}")
            )
        response_json = cast("Mapping[str, RPC_JSON]", response_json)

        # Note that the Eth-side errors (e.g. transaction having been reverted)
        # will have the HTTP status 200, so we are checking for the "error" field first.
        if "error" in response_json:
            try:
                error = structure(RPCError, response_json["error"])
            except StructuringError as exc:
                raise ProviderError(
                    InvalidResponse(f"Failed to parse an error response: {response_json}")
                ) from exc

            raise ProviderError(error)

        if status == HTTPStatus.OK:
            if "result" in response_json:
                return response_json["result"]
            raise ProviderError(
                InvalidResponse(f"`result` is not present in the response: {response_json}")
            )

        raise ProviderError(HTTPError(status, response.content.decode()))
