"""ASGI wrapper that authenticates every request to /mcp before the MCP transport sees it."""

from __future__ import annotations

import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from sf_mcp.auth.authenticator import Authenticator, AuthFailure

security_log = logging.getLogger("sf_mcp.security")


class MCPAuthApp:
    def __init__(self, inner: ASGIApp, authenticator: Authenticator) -> None:
        self._inner = inner
        self._authenticator = authenticator

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._inner(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        peer = scope.get("client")
        peer_host = peer[0] if peer else None
        try:
            principal = await self._authenticator.authenticate(headers, peer_host)
        except AuthFailure as failure:
            security_log.warning(
                "auth failure",
                extra={"event": "auth_failure", "reason": failure.reason, "key_id": failure.key_id},
            )
            response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="sf-mcp"', "Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        scope.setdefault("state", {})["principal"] = principal
        await self._inner(scope, receive, send)
