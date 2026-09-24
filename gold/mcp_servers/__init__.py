"""MCP tool servers. Each one is a small HTTP service any MCP client can use."""

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from gold import config


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
    uvicorn.run(app, host=config.HOST, port=config.PORT)
