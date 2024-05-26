from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from http import HTTPStatus
from json import JSONDecodeError
from typing import cast

import httpx
from compages import StructuringError
from ethereum_rpc import JSON, RPCError, structure


class InvalidResponse(Exception):
    """Raised when the remote server's response is not of an expected format."""


class Unreachable(Exception):
    """Raised when there is a problem connecting to the provider."""


class ProtocolError(Exception):
    """A protocol-specific error."""


class HTTPError(ProtocolError):
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

    The methods of this class may raise the following exceptions:
    - :py:class:`RPCError` signifies an error coming from the backend provider;
    - :py:class:`Unreachable` if the provider is unreachable;
    - :py:class:`InvalidResponse` if the response was received but could not be parsed;
    - :py:class:`ProtocolError` if there was an unrecognized error on the protocol level
      (e.g. an HTTP status code that is not 200 or 400).

    All other exceptions can be considered implementation bugs.
    """

    @abstractmethod
    async def rpc(self, method: str, *args: JSON) -> JSON:
        """Calls the given RPC method with the already json-ified arguments."""
        ...

    async def rpc_and_pin(self, method: str, *args: JSON) -> tuple[JSON, tuple[int, ...]]:
        """
        Calls the given RPC method and returns the path to the provider it succeded on.
        This method will be typically overriden by multi-provider implementations.
        """
        return await self.rpc(method, *args), ()

    async def rpc_at_pin(self, path: tuple[int, ...], method: str, *args: JSON) -> JSON:
        """
        Calls the given RPC method at the provider by the given path
        (obtained previously from ``rpc_and_pin()``).
        This method will be typically overriden by multi-provider implementations.
        """
        if path != ():
            raise ValueError(f"Unexpected provider path: {path}")
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

    def _prepare_request(self, method: str, *args: JSON) -> JSON:
        return {"jsonrpc": "2.0", "method": method, "params": args, "id": 0}

    async def rpc(self, method: str, *args: JSON) -> JSON:
        json = self._prepare_request(method, *args)
        try:
            response = await self._client.post(self._url, json=json)
        except httpx.ConnectError as exc:
            raise Unreachable(str(exc)) from exc

        status = response.status_code

        try:
            response_json = response.json()
        except JSONDecodeError as exc:
            content = response.content.decode()
            raise InvalidResponse(
                f"Expected a JSON response, got HTTP status {status}: {content}"
            ) from exc

        if not isinstance(response_json, Mapping):
            raise InvalidResponse(f"RPC response must be a dictionary, got: {response_json}")
        response_json = cast(Mapping[str, JSON], response_json)

        # Note that the Eth-side errors (e.g. transaction having been reverted)
        # will have the HTTP status 200, so we are checking for the "error" field first.
        if "error" in response_json:
            try:
                error = structure(RPCError, response_json["error"])
            except StructuringError as exc:
                raise InvalidResponse(
                    f"Failed to parse an error response: {response_json}"
                ) from exc

            raise error

        if status == HTTPStatus.OK:
            if "result" in response_json:
                return response_json["result"]
            raise InvalidResponse(f"`result` is not present in the response: {response_json}")

        raise HTTPError(status, response.content.decode())
