from abc import ABC, abstractmethod
from typing import Any

import httpx


class Provider(ABC):

    @abstractmethod
    async def rpc_call(self, method: str, *args) -> Any:
        ...


class HTTPProvider:

    def __init__(self, url):
        self._url = url

    async def rpc_call(self, method, *args):
        json = {
            "jsonrpc": "2.0",
            "method": method,
            "params": list(args),
            "id": 0
            }
        async with httpx.AsyncClient() as client:
            response = await client.post(self._url, json=json)
        response_json = response.json()
        if 'error' in response_json:
            code = response_json['error']['code']
            message = response_json['error']['message']
            raise RuntimeError(f"RPC error {code}: {message}")
        if 'result' not in response_json:
            raise Exception(response_json)
        return response_json['result']
