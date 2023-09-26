import http
from typing import Iterable, cast

import trio
from hypercorn.config import Config
from hypercorn.trio import serve
from hypercorn.typing import ASGIFramework
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from trio_typing import TaskStatus

from ._provider import JSON, HTTPProvider, Provider, ResponseDict, RPCError


async def process_request(provider: Provider, data: JSON) -> JSON:
    """
    Partially parses the incoming JSON RPC request, passes it to the VM wrapper,
    and wraps the results in a JSON RPC formatted response.
    """
    request = ResponseDict(data)
    request_id = request["id"]
    try:
        if not isinstance(request["method"], str):
            raise RuntimeError("`method` field must be a string")  # noqa: TRY004
        if not isinstance(request["params"], Iterable):
            raise RuntimeError("`params` field must be a list")  # noqa: TRY004
        params = list(request["params"])
        async with provider.session() as session:
            result = await session.rpc(request["method"], *params)
    except RPCError as e:
        error = {"code": e.code, "message": e.message, "data": e.data}
        return {"jsonrpc": "2.0", "id": request_id, "error": error}

    return {"jsonrpc": "2.0", "id": request_id, "result": result}


async def entry_point(request: Request) -> Response:
    data = await request.json()
    provider = request.app.state.provider
    try:
        result = await process_request(provider, data)
    except Exception as e:  # noqa: BLE001
        # A catch-all for any unexpected errors
        return Response(str(e), status_code=http.HTTPStatus.INTERNAL_SERVER_ERROR)

    return JSONResponse(result)


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


class ServerHandle:
    """
    A handle for a running web server.
    Can be used to shut it down.
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
        self._shutdown_event.set()
        await self._shutdown_finished.wait()
