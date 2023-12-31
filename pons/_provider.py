from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from enum import Enum
from http import HTTPStatus
from typing import AsyncIterator, Dict, Iterable, Mapping, Optional, Tuple, Union, cast

import httpx

# TODO: the doc entry had to be written manually for this type because of Sphinx limitations.
JSON = Union[bool, int, float, str, None, Iterable["JSON"], Mapping[str, "JSON"]]


class RPCErrorCode(Enum):
    """Known RPC error codes returned by providers."""

    # This is our placeholder value, shouldn't be encountered in a remote server response
    UNKNOWN_REASON = 0
    """An error code whose description is not present in this enum."""

    SERVER_ERROR = -32000
    """Reserved for implementation-defined server-errors. See the message for details."""

    INVALID_REQUEST = -32600
    """The JSON sent is not a valid Request object."""

    METHOD_NOT_FOUND = -32601
    """The method does not exist / is not available."""

    INVALID_PARAMETER = -32602
    """Invalid method parameter(s)."""

    EXECUTION_ERROR = 3
    """Contract transaction failed during execution. See the data for details."""

    @classmethod
    def from_int(cls, val: int) -> "RPCErrorCode":
        try:
            return cls(val)
        except ValueError:
            return cls.UNKNOWN_REASON


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


class RPCError(Exception):
    """A wrapper for a call execution error returned as a proper RPC response."""

    @classmethod
    def from_json(cls, response: JSON) -> "RPCError":
        error = ResponseDict(response)
        if "data" in error:
            data = error["data"]
            if data is not None and not isinstance(data, str):
                raise InvalidResponse(
                    f"Error data must be a string or None, got {type(data)} ({data})"
                )
        else:
            data = None

        error_code = error["code"]
        if isinstance(error_code, str):
            code = int(error_code)
        elif isinstance(error_code, int):
            code = error_code
        else:
            raise InvalidResponse(
                "Error code must be an integer (possibly string-encoded), "
                f"got {type(error_code)} ({error_code})"
            )

        message = error["message"]
        if not isinstance(message, str):
            raise InvalidResponse(
                f"Error message must be a string, got {type(message)} ({message})"
            )

        return cls(code, message, data)

    @classmethod
    def invalid_request(cls) -> "RPCError":
        return cls(RPCErrorCode.INVALID_REQUEST.value, "invalid json request")

    @classmethod
    def method_not_found(cls, method: str) -> "RPCError":
        return cls(
            RPCErrorCode.METHOD_NOT_FOUND.value,
            f"The method {method} does not exist/is not available",
        )

    @classmethod
    def invalid_parameter(cls, message: str) -> "RPCError":
        return cls(RPCErrorCode.INVALID_PARAMETER.value, message)

    def __init__(self, code: int, message: str, data: Optional[str] = None):
        # Taking an integer and not `RPCErrorCode` here
        # since the codes may differ between providers.
        super().__init__(code, message, data)
        self.code = code
        self.message = message
        self.data = data

    def to_json(self) -> JSON:
        result = {"code": self.code, "message": self.message}
        if self.data:
            result["data"] = self.data
        return result


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


class ResponseDict:
    """
    A wrapper for dictionaries allowing as to narrow down KeyErrors
    resulting from a JSON object of an incorrect format.
    """

    def __init__(self, obj: JSON):
        if not isinstance(obj, dict):
            raise InvalidResponse(f"Expected a dictionary as a response, got {type(obj).__name__}")
        self._obj = cast(Dict[str, JSON], obj)

    def __contains__(self, field: str) -> bool:
        return field in self._obj

    def __getitem__(self, field: str) -> JSON:
        try:
            contents = self._obj[field]
        except KeyError as exc:
            raise InvalidResponse(f"Expected field `{field}` is missing from the result") from exc
        return contents


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

    async def rpc_and_pin(self, method: str, *args: JSON) -> Tuple[JSON, Tuple[int, ...]]:
        """
        Calls the given RPC method and returns the path to the provider it succeded on.
        This method will be typically overriden by multi-provider implementations.
        """
        return await self.rpc(method, *args), ()

    async def rpc_at_pin(self, path: Tuple[int, ...], method: str, *args: JSON) -> JSON:
        """
        Calls the given RPC method at the provider by the given path
        (obtained previously from ``rpc_and_pin()``).
        This method will be typically overriden by multi-provider implementations.
        """
        if path != ():
            raise ValueError(f"Unexpected provider path: {path}")
        return await self.rpc(method, *args)

    async def rpc_dict(self, method: str, *args: JSON) -> Optional[ResponseDict]:
        """Calls the given RPC method expecting to get a dictionary (or ``null``) in response."""
        result = await self.rpc(method, *args)
        if result is None:
            return None
        return ResponseDict(result)


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
        if response.status_code not in (HTTPStatus.OK, HTTPStatus.BAD_REQUEST):
            raise HTTPError(response.status_code, response.content.decode())

        # Assuming that the HTTP client knows what it's doing, and gives us a valid JSON dict
        response_json = response.json()
        if not isinstance(response_json, Mapping):
            raise InvalidResponse(f"RPC response must be a dictionary, got: {response_json}")
        response_json = cast(Mapping[str, JSON], response_json)

        if response.status_code == HTTPStatus.BAD_REQUEST and "error" in response_json:
            raise RPCError.from_json(response_json["error"])

        if response.status_code == HTTPStatus.OK and "result" in response_json:
            return response_json["result"]

        raise InvalidResponse("`result` is not present in the response")
