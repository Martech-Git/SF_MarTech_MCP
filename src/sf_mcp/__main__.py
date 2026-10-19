"""Entry point: `python -m sf_mcp`. Cloud Run sets PORT."""

from __future__ import annotations

import uvicorn
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware

from sf_mcp.app import create_app
from sf_mcp.config import load_settings
from sf_mcp.logging_setup import configure_logging
from sf_mcp.telemetry import configure_tracing


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level, settings.gcp_project)
    configure_tracing(settings)
    app = OpenTelemetryMiddleware(create_app(settings), excluded_urls="healthz")
    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 - Cloud Run routes traffic to the container port
        port=settings.port,
        access_log=False,
        proxy_headers=False,
        server_header=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
