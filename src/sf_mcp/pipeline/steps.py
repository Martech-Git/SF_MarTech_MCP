"""The ten enforcement steps. Each step raises `Denied` to stop the call; none can be skipped.

Steps 5 and 7 have no rules to apply for tools without a Salesforce backend. For any tool that has
one, they deny until milestones 3 and 4 build the allowlists and content rules.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from sf_mcp.errors import Denied, ErrorCode
from sf_mcp.pipeline.context import CallContext, PipelineDeps
from sf_mcp.policy.evaluator import authorize
from sf_mcp.tools.registry import Tier, ToolContext

Step = Callable[[CallContext, PipelineDeps], Awaitable[None]]


class ToolFailure(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def s01_authenticate(ctx: CallContext, deps: PipelineDeps) -> None:
    # The HTTP layer already rejected unauthenticated requests; this repeats the check in depth.
    if ctx.principal is None:
        raise Denied(ErrorCode.UNAUTHENTICATED, "auth.missing", "Request is not authenticated.")
    ctx.bundle = deps.policy()


async def s02_kill_switches(ctx: CallContext, deps: PipelineDeps) -> None:
    state = await deps.killswitches.current()
    ctx.switches = state
    if state.global_off:
        raise Denied(ErrorCode.KILL_SWITCH, "kill.global", "The server is switched off by an administrator.")
    if ctx.tool_name in state.tools_off:
        raise Denied(ErrorCode.KILL_SWITCH, "kill.tool", "This tool is switched off by an administrator.")
    raw_bu = ctx.raw_args.get("bu")
    if isinstance(raw_bu, str) and raw_bu in state.bus_off:
        raise Denied(
            ErrorCode.KILL_SWITCH, "kill.bu", "This business unit is switched off by an administrator."
        )
    spec = deps.registry.get(ctx.tool_name)
    if state.read_only and spec is not None and spec.tier is not Tier.T0:
        raise Denied(ErrorCode.KILL_SWITCH, "kill.read_only", "The server is in read-only mode.")


async def s03_schema(ctx: CallContext, deps: PipelineDeps) -> None:
    spec = deps.registry.get(ctx.tool_name)
    if spec is None:
        raise Denied(ErrorCode.NOT_FOUND, "tool.unknown", "Unknown tool.")
    ctx.spec = spec
    try:
        args = spec.input_model.model_validate(dict(ctx.raw_args), strict=True)
    except ValidationError as exc:
        # Report where and what kind of error, never the offending values.
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['type']}" for err in exc.errors()
        )
        raise Denied(ErrorCode.VALIDATION, "schema.invalid", f"Invalid arguments: {problems}") from None
    ctx.args = args
    bu = getattr(args, "bu", None)
    ctx.bu = bu if isinstance(bu, str) else None
    mode = getattr(args, "mode", None)
    ctx.mode = mode if isinstance(mode, str) else None


async def s04_authorize(ctx: CallContext, deps: PipelineDeps) -> None:
    assert ctx.principal is not None
    assert ctx.spec is not None
    assert ctx.bundle is not None
    decision = authorize(ctx.principal.client, ctx.spec, ctx.bu, ctx.bundle, deps.environment)
    if not decision.allowed:
        raise Denied(ErrorCode.PERMISSION, decision.rule_id, "This client is not granted this tool here.")
    ctx.allow_rule = decision.rule_id


async def s05_allowlists(ctx: CallContext, deps: PipelineDeps) -> None:
    assert ctx.spec is not None
    if ctx.spec.backend != "none":
        raise Denied(
            ErrorCode.NOT_ENABLED, "allowlist.not_built", "Resource allowlists arrive in milestone 3."
        )


async def s06_limits(ctx: CallContext, deps: PipelineDeps) -> None:
    assert ctx.principal is not None
    assert ctx.spec is not None
    assert ctx.bundle is not None
    limits = ctx.bundle.limits
    tool_policy = ctx.bundle.tools[ctx.spec.name]
    per_key = tool_policy.per_key_per_minute or limits.per_key_per_minute
    if not deps.rate_limiter.allow(f"key:{ctx.principal.key_id}:{ctx.spec.name}", per_key):
        raise Denied(ErrorCode.RATE_LIMITED, "limit.key", "Rate limit reached for this key. Retry shortly.")
    if ctx.bu is not None and not deps.rate_limiter.allow(f"bu:{ctx.bu}", limits.per_bu_per_minute):
        raise Denied(ErrorCode.RATE_LIMITED, "limit.bu", "Rate limit reached for this business unit.")
    if ctx.spec.backend == "sfmc" and not deps.rate_limiter.allow(
        "tenant:sfmc", limits.tenant_sync_per_minute
    ):
        raise Denied(ErrorCode.RATE_LIMITED, "limit.tenant", "Rate limit reached for the SFMC tenant.")


async def s07_content_rules(ctx: CallContext, deps: PipelineDeps) -> None:
    assert ctx.spec is not None
    if ctx.spec.backend != "none":
        raise Denied(
            ErrorCode.NOT_ENABLED, "content.not_built", "Content and data rules arrive in milestone 4."
        )


async def s08_tier(ctx: CallContext, deps: PipelineDeps) -> None:
    assert ctx.spec is not None
    if ctx.spec.tier is not Tier.T0:
        raise Denied(ErrorCode.NOT_ENABLED, "tier.not_built", "Write tiers arrive in milestones 4 and 5.")


async def s09_execute(ctx: CallContext, deps: PipelineDeps) -> None:
    assert ctx.spec is not None
    assert ctx.args is not None
    assert ctx.bundle is not None
    switches = ctx.switches
    tool_ctx = ToolContext(
        environment=deps.environment,
        policy_version=ctx.bundle.version,
        read_only=bool(switches and switches.read_only),
        now=deps.clock.now(),
    )
    try:
        ctx.result = await asyncio.wait_for(
            ctx.spec.handler(ctx.args, tool_ctx), deps.handler_timeout_seconds
        )
    except TimeoutError:
        raise ToolFailure(ErrorCode.INTERNAL, "The tool timed out.") from None


STEPS: tuple[tuple[str, Step], ...] = (
    ("01_authenticate", s01_authenticate),
    ("02_kill_switches", s02_kill_switches),
    ("03_schema", s03_schema),
    ("04_authorize", s04_authorize),
    ("05_allowlists", s05_allowlists),
    ("06_limits", s06_limits),
    ("07_content_rules", s07_content_rules),
    ("08_tier", s08_tier),
    ("09_execute", s09_execute),
)
