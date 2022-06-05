import http

from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hypercorn.config import Config
from hypercorn.trio import serve
import trio

from pons import HTTPProvider
from pons._provider import RPCError


async def process_request(provider, data):
    request_id = data["id"]
    try:
        async with provider.session() as session:
            result = await session.rpc(data["method"], *data["params"])
    except RPCError as e:
        error = {"code": e.code, "message": e.message, "data": e.data}
        return {"jsonrpc": "2.0", "id": request_id, "error": error}

    return {"jsonrpc": "2.0", "id": request_id, "result": result}


async def entry_point(request):
    data = await request.json()
    provider = request.app.state.provider
    try:
        result = await process_request(provider, data)
    except Exception as e:
        # A catch-all for any unexpected errors
        return Response(str(e), status_code=http.HTTPStatus.INTERNAL_SERVER_ERROR)

    return JSONResponse(result)


def make_app(provider):
    """
    Creates and returns an ASGI app.
    """

    # Since we need to use an externally passed context in the app (``ursula_server``),
    # we have to create the app inside a function.

    routes = [
        Route("/", entry_point, methods=["POST"]),
    ]

    app = Starlette(routes=routes)
    app.state.provider = provider

    return app


class ServerHandle:
    """
    A handle for a running web server.
    Can be used to shut it down.
    """

    def __init__(self, provider, host="127.0.0.1", port=8888):
        self._host = host
        self._port = port
        self._provider = provider
        self._shutdown_event = trio.Event()
        self.http_provider = HTTPProvider(f"http://{self._host}:{self._port}")

    async def __call__(self, *, task_status=trio.TASK_STATUS_IGNORED):
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

    def shutdown(self):
        self._shutdown_event.set()
