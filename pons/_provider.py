from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

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
        response = await self._client.post(self._url, json=json)
        response_json = response.json()
        if 'error' in response_json:
            code = response_json['error']['code']
            message = response_json['error']['message']
            raise RuntimeError(f"RPC error {code}: {message}")
        if 'result' not in response_json:
            raise Exception(response_json)
        return response_json['result']
