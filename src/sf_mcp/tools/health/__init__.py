from __future__ import annotations

from sf_mcp.tools.health.handler import handle
from sf_mcp.tools.health.schema import HealthInput
from sf_mcp.tools.registry import Role, Tier, ToolSpec, load_description

SPEC = ToolSpec(
    name="health",
    title="Server health",
    tier=Tier.T0,
    min_role=Role.VIEWER,
    bu_scoped=False,
    backend="none",
    input_model=HealthInput,
    handler=handle,
    description=load_description(__name__),
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
)
