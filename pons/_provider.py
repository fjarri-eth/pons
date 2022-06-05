from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Any, AsyncIterator, Dict, Optional

import httpx


class Provider(ABC):
    """
    The base class for JSON RPC providers.
    """

    @abstractmethod
    @asynccontextmanager
    async def session(self) -> AsyncIterator["ProviderSession"]:
        """
        Opens a session to the provider
        (allowing the backend to perform multiple operations faster).
        """
        yield  # type: ignore


class UnexpectedResponse(Exception):
    """
    Raised when the remote server's response is not of an expected format.
    """


class ResponseDict:
    """
    A wrapper for dictionaries allowing as to narrow down KeyErrors
    resulting from an incorrectly formatted response.
    """

    def __init__(self, response: Dict[str, Any]):
        if not isinstance(response, dict):
            raise UnexpectedResponse(
                f"Expected a dictionary as a response, got {type(response).__name__}"
            )
        self._response = response

    def __contains__(self, field: str):
        return field in self._response

    def __getitem__(self, field: str) -> Any:
        try:
            contents = self._response[field]
        except KeyError as exc:
            raise UnexpectedResponse(
                f"Expected field `{field}` is missing from the result"
            ) from exc
        return contents


class ProviderSession(ABC):
    """
    The base class for provider sessions.
    """

    @abstractmethod
    async def rpc(self, method: str, *args) -> Any:
        """
        Calls the given RPC method with the already json-ified arguments.
        """
        ...

    async def rpc_dict(self, method: str, *args) -> Optional[ResponseDict]:
        result = await self.rpc(method, *args)
        if result is None:
            return None
        else:
            return ResponseDict(result)


class HTTPProvider(Provider):
    """
    A provider for RPC via HTTP(S).
    """

    def __init__(self, url: str):
        self._url = url

    @asynccontextmanager
    async def session(self) -> AsyncIterator["HTTPSession"]:
        async with httpx.AsyncClient() as client:
            yield HTTPSession(self._url, client)


class RPCError(Exception):
    """
    A wrapper for a server error returned either as a proper RPC response,
    or as an HTTP error code response.
    """

    @classmethod
    def from_json(cls, response: Dict[str, Any]):
        error = ResponseDict(response)
        data = error["data"] if "data" in error else None
        code = int(error["code"])
        return cls(code, error["message"], data)

    def __init__(self, code: int, message: str, data: Optional[str] = None):
        super().__init__(code, message, data)
        self.code = code
        self.message = message
        self.data = data


class Unreachable(Exception):
    """
    Raised when there is a problem connecting to the provider.
    """


class HTTPSession(ProviderSession):
    def __init__(self, url: str, http_client: httpx.AsyncClient):
        self._url = url
        self._client = http_client

    async def rpc(self, method: str, *args):
        json = {"jsonrpc": "2.0", "method": method, "params": list(args), "id": 0}
        try:
            response = await self._client.post(self._url, json=json)
        except Exception as exc:
            raise Unreachable(str(exc)) from exc
        if response.status_code != HTTPStatus.OK:
            raise RPCError(response.status_code, response.content.decode())

        response_json = response.json()
        if "error" in response_json:
            raise RPCError.from_json(response_json["error"])
        if "result" not in response_json:
            raise UnexpectedResponse(f"`result` is not present in the response: {response_json}")
        return response_json["result"]
