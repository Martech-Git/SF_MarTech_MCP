from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from sf_mcp import __version__
from sf_mcp.tools.health import SPEC
from sf_mcp.tools.health.handler import handle
from sf_mcp.tools.health.schema import HealthInput
from sf_mcp.tools.registry import Tier, ToolContext


async def test_health_reports_environment_and_policy_version() -> None:
    ctx = ToolContext(
        environment="dev", policy_version="abc123", read_only=True, now=datetime(2026, 1, 1, tzinfo=UTC)
    )
    out = await handle(HealthInput(), ctx)
    assert out.status == "ok"
    assert out.version == __version__
    assert out.environment == "dev"
    assert out.policy_version == "abc123"
    assert out.read_only is True


def test_health_rejects_unknown_arguments() -> None:
    with pytest.raises(ValidationError):
        HealthInput.model_validate({"unexpected": 1})


def test_health_is_a_read_only_t0_tool() -> None:
    assert SPEC.tier is Tier.T0
    tool = SPEC.to_mcp()
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.input_schema.get("additionalProperties") is False
