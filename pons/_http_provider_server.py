from http import HTTPStatus
from typing import cast

import trio
from hypercorn.config import Config
from hypercorn.trio import serve
from hypercorn.typing import ASGIFramework
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from trio_typing import TaskStatus

from ._entities import RPCError
from ._provider import JSON, HTTPProvider, Provider
from ._serialization import unstructure


def parse_request(request: JSON) -> tuple[JSON, str, list[JSON]]:
    request = cast(dict[str, JSON], request)
    request_id = request["id"]
    method = request["method"]
    if not isinstance(method, str):
        raise TypeError("The method name must be a string")
    params = request["params"]
    if not isinstance(params, list):
        raise TypeError("The method parameters must be a list")
    return (request_id, method, params)


async def process_request_inner(provider: Provider, request: JSON) -> tuple[JSON, JSON]:
    try:
        request_id, method, params = parse_request(request)
    except (KeyError, TypeError) as exc:
        raise RPCError.invalid_request() from exc

    async with provider.session() as session:
        result = await session.rpc(method, *params)

    return request_id, result


async def process_request(provider: Provider, request: JSON) -> tuple[HTTPStatus, JSON]:
    """
    Partially parses the incoming JSON RPC request, passes it to the VM wrapper,
    and wraps the results in a JSON RPC formatted response.
    """
    try:
        request_id, result = await process_request_inner(provider, request)
    except RPCError as exc:
        return HTTPStatus.BAD_REQUEST, {"jsonrpc": "2.0", "error": unstructure(exc)}

    return HTTPStatus.OK, {"jsonrpc": "2.0", "id": request_id, "result": result}


async def entry_point(request: Request) -> Response:
    data = await request.json()
    provider = request.app.state.provider
    try:
        status, response = await process_request(provider, data)
    except Exception as exc:  # noqa: BLE001
        # A catch-all for any unexpected errors
        return Response(str(exc), status_code=HTTPStatus.INTERNAL_SERVER_ERROR)

    return JSONResponse(response, status_code=status)


def make_app(provider: Provider) -> ASGIFramework:
    """Creates and returns an ASGI app."""
    routes = [
        Route("/", entry_point, methods=["POST"]),
    ]

    app = Starlette(routes=routes)
    app.state.provider = provider

    # We don't have a typing package shared between Starlette and Hypercorn,
    # so this will have to do
    return cast(ASGIFramework, app)


class HTTPProviderServer:
    """
    A server counterpart of :py:class:`pons.HTTPProvider`.
    Intended for testing, not production-ready.
    """

    def __init__(self, provider: Provider, host: str = "127.0.0.1", port: int = 8888):
        self._host = host
        self._port = port
        self._provider = provider
        self._shutdown_event = trio.Event()
        self._shutdown_finished = trio.Event()
        self.http_provider = HTTPProvider(f"http://{self._host}:{self._port}")

    async def __call__(self, *, task_status: TaskStatus[None] = trio.TASK_STATUS_IGNORED) -> None:
        """
        Starts the server in an external event loop.
        Useful for the cases when it needs to run in parallel with other servers or clients.

        Supports start-up reporting when invoked via `nursery.start()`.
        """
        config = Config()
        config.bind = [f"{self._host}:{self._port}"]
        config.worker_class = "trio"
        app = make_app(self._provider)
        await serve(
            app, config, shutdown_trigger=self._shutdown_event.wait, task_status=task_status
        )
        self._shutdown_finished.set()

    async def shutdown(self) -> None:
        """Shuts down the server."""
        self._shutdown_event.set()
        await self._shutdown_finished.wait()
