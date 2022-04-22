from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from enum import Enum
from http import HTTPStatus
from typing import Any, AsyncIterator, Dict, Optional, Union

import httpx


class Provider(ABC):
    """
    The base class for JSON RPC providers.
    """

    @abstractmethod
    @asynccontextmanager
    async def session(self) -> AsyncIterator['ProviderSession']:
        """
        Opens a session to the provider
        (allowing the backend to perform multiple operations faster).
        """
        yield # type: ignore


class MissingField(Exception):
    pass


class UnexpectedResponseType(Exception):
    pass


class ResponseDict:
    """
    A wrapper for dictionaries allowing as to narrow down KeyErrors
    resulting from an incorrectly formatted response.
    """

    def __init__(self, response: Dict[str, Any]):
        if not isinstance(response, dict):
            raise UnexpectedResponseType(
                f"expected a dictionary as a response, got {type(response).__name__}")
        self._response = response

    def __contains__(self, field: str):
        return field in self._response

    def __getitem__(self, field: str) -> Any:
        try:
            contents = self._response[field]
        except KeyError as e:
            raise MissingField(str(e)) from e
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
    async def session(self) -> AsyncIterator['HTTPSession']:
        async with httpx.AsyncClient() as client:
            yield HTTPSession(self._url, client)


class RPCErrorCode(Enum):
    # This is our placeholder value, shouldn't be encountered in a remote server response
    UNKNOWN_REASON = 0

    SERVER_ERROR = -32000
    """Reserved for implementation-defined server-errors. See the message for details."""

    EXECUTION_ERROR = 3
    """Contract transaction failed during execution. See the data for details."""

    @classmethod
    def from_json(cls, val: Union[int, str]):
        val = int(val)
        try:
            return cls(val)
        except Exception as e:
            return cls.UNKNOWN_REASON


class RPCError(Exception):

    @classmethod
    def from_json(cls, response: Dict[str, Any]):
        error = ResponseDict(response)
        data = error['data'] if 'data' in error else None
        return cls(error['code'], error['message'], data)

    def __init__(self, server_code: Union[int, str], message: str, data: Optional[Any] = None):
        super().__init__(server_code, message, data)
        self.server_code = server_code
        self.code = RPCErrorCode.from_json(server_code)
        self.message = message
        self.data = data


class HTTPSession(ProviderSession):

    def __init__(self, url: str, http_client: httpx.AsyncClient):
        self._url = url
        self._client = http_client

    async def rpc(self, method: str, *args):
        json = {
            "jsonrpc": "2.0",
            "method": method,
            "params": list(args),
            "id": 0
            }
        # TODO: wrap possible connection errors (anything that doesn't lead to an actual response)
        response = await self._client.post(self._url, json=json)
        if response.status_code != HTTPStatus.OK:
            # TODO: use our own error class
            raise RuntimeError(
                f"Request failed with status {response.status_code}, contents: {response.content}")

        response_json = response.json()
        if 'error' in response_json:
            raise RPCError.from_json(response_json['error'])
        if 'result' not in response_json:
            raise UnexpectedResponseType(response_json)
        return response_json['result']
