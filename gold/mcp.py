"""MCP tool servers: helpers every app's tool server uses. Each server is a small HTTP service any MCP client can use."""

import uvicorn
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from gold import config, identity, telemetry

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)
# A tool that changes something. Pair it with gold.approvals so a person approves each call.
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True)


def header(ctx: Context, name: str) -> str | None:
    request = getattr(ctx.request_context, "request", None)
    return request.headers.get(name) if request is not None else None


def current_user(ctx: Context) -> identity.User | None:
    """The signed-in user the calling agent acts for. Raises identity.AuthError if the context is forged or expired."""
    return identity.verify(header(ctx, identity.HEADER))


def serve(server: MCPServer) -> None:
    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        host=config.HOST,
        # Inside Docker or Kubernetes the Host header is a service name, so
        # DNS-rebinding protection (meant for servers on a laptop) is off.
        # Put authentication in front of this in production.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    uvicorn.run(telemetry.wrap(app, server.name.removeprefix("gold-")), host=config.HOST, port=config.PORT)
