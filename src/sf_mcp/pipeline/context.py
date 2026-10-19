"""State carried through one tool call, and the dependencies every step may use."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from sf_mcp.audit import Auditor
from sf_mcp.auth.authenticator import ClientPrincipal
from sf_mcp.clock import Clock
from sf_mcp.killswitch import CachedKillSwitches, KillSwitchState
from sf_mcp.policy.loader import PolicyBundle
from sf_mcp.ratelimit import RateLimiter
from sf_mcp.tools.registry import ToolSpec


@dataclass(frozen=True, slots=True)
class PipelineDeps:
    environment: str
    registry: Mapping[str, ToolSpec]
    policy: Callable[[], PolicyBundle]
    killswitches: CachedKillSwitches
    rate_limiter: RateLimiter
    auditor: Auditor
    clock: Clock
    handler_timeout_seconds: float = 10.0


@dataclass(slots=True)
class CallContext:
    tool_call_id: str
    tool_name: str
    raw_args: Mapping[str, Any]
    principal: ClientPrincipal | None
    started_monotonic: float
    trace_id: str | None
    bundle: PolicyBundle | None = None
    spec: ToolSpec | None = None
    args: BaseModel | None = None
    bu: str | None = None
    mode: str | None = None
    switches: KillSwitchState | None = None
    allow_rule: str = "pending"
    result: BaseModel | None = None
    targets: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
