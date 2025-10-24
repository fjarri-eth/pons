"""HTTP provider based on `httpx`."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from http import HTTPStatus
from json import JSONDecodeError
from typing import cast

import httpx
from compages import StructuringError
from ethereum_rpc import RPCError, structure

from ._provider import (
    RPC_JSON,
    InvalidResponse,
    ProtocolError,
    Provider,
    ProviderError,
    ProviderSession,
    Unreachable,
)

__all__ = ["HTTPError", "HTTPProvider"]


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

    def __str__(self) -> str:  # noqa: D105
        return f"HTTP status {self.status}: {self.message}"


class HTTPProvider(Provider):
    """A provider for RPC via HTTP(S)."""

    def __init__(self, url: str):
        self._url = url

    @asynccontextmanager
    async def session(self) -> AsyncIterator["HTTPProviderSession"]:  # noqa: D102
        async with httpx.AsyncClient() as client:
            yield HTTPProviderSession(self._url, client)


class HTTPProviderSession(ProviderSession):
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
