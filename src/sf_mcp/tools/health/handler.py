from __future__ import annotations

from sf_mcp import SERVICE_NAME, __version__
from sf_mcp.tools.health.schema import HealthInput, HealthOutput
from sf_mcp.tools.registry import ToolContext


async def handle(args: HealthInput, ctx: ToolContext) -> HealthOutput:
    return HealthOutput(
        status="ok",
        service=SERVICE_NAME,
        version=__version__,
        environment=ctx.environment,
        policy_version=ctx.policy_version,
        read_only=ctx.read_only,
        time=ctx.now.isoformat(),
    )
