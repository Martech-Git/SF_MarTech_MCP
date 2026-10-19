"""Runs steps 1 to 9 in order, then step 10 (verify and audit) on every outcome.

If the audit write fails, the caller gets an error and no data: nothing leaves the server unaudited.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from sf_mcp.audit.events import ClientRef, PolicyRef, ToolAuditEvent, sha256_hex
from sf_mcp.errors import Denied, ErrorCode
from sf_mcp.pipeline.context import CallContext, PipelineDeps
from sf_mcp.pipeline.steps import STEPS, ToolFailure
from sf_mcp.telemetry import tracer

log = logging.getLogger("sf_mcp.pipeline")

Status = Literal["ok", "denied", "error"]


def _envelope(
    ctx: CallContext, status: Status, data: dict[str, Any] | None, code: str | None, message: str | None
) -> dict[str, Any]:
    return {
        "status": status,
        "data": data,
        "error": None if code is None else {"code": code, "message": message},
        "meta": {
            "tool_call_id": ctx.tool_call_id,
            "policy_version": ctx.bundle.version if ctx.bundle else None,
            "bu": ctx.bu,
            "truncated": False,
            "next_cursor": None,
        },
    }


def _audit_event(
    ctx: CallContext, deps: PipelineDeps, outcome: str, denied: Denied | None, error_code: str | None
) -> ToolAuditEvent:
    principal = ctx.principal
    client = (
        ClientRef(
            key_id=principal.key_id, client_id=principal.client.client_id, owner=str(principal.client.owner)
        )
        if principal
        else ClientRef(key_id="none", client_id="none", owner="none")
    )
    policy = (
        PolicyRef(
            decision="deny", rule_id=denied.rule_id, version=ctx.bundle.version if ctx.bundle else "none"
        )
        if denied
        else PolicyRef(
            decision="allow", rule_id=ctx.allow_rule, version=ctx.bundle.version if ctx.bundle else "none"
        )
    )
    duration_ms = int((deps.clock.monotonic() - ctx.started_monotonic) * 1000)
    return ToolAuditEvent(
        tool_call_id=ctx.tool_call_id,
        trace_id=ctx.trace_id,
        timestamp=deps.clock.now(),
        client=client,
        asserted_user=principal.asserted_user if principal else None,
        tool=ctx.tool_name[:128],
        tier=ctx.spec.tier.name if ctx.spec else None,
        mode=ctx.mode,
        bu=ctx.bu,
        environment=deps.environment,
        targets=list(ctx.targets),
        input_hash=sha256_hex(dict(ctx.raw_args)),
        output_hash=sha256_hex(ctx.result.model_dump(mode="json")) if ctx.result is not None else None,
        counts=dict(ctx.counts),
        policy=policy,
        error_code=error_code,
        outcome=outcome,  # type: ignore[arg-type]
        duration_ms=duration_ms,
    )


async def run_tool_call(ctx: CallContext, deps: PipelineDeps) -> dict[str, Any]:
    denied: Denied | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    outcome = "success"

    with tracer.start_as_current_span(
        "sfmcp.tool_call", attributes={"sfmcp.tool": ctx.tool_name[:128]}
    ) as span:
        try:
            for name, step in STEPS:
                with tracer.start_as_current_span(f"sfmcp.step.{name}"):
                    await step(ctx, deps)
        except Denied as exc:
            denied = exc
            outcome = "denied"
        except ToolFailure as exc:
            outcome = "failed"
            failure_code, failure_message = exc.code.value, exc.message
        except Exception:
            outcome = "failed"
            failure_code, failure_message = ErrorCode.INTERNAL.value, "The tool failed."
            log.exception(
                "tool call failed", extra={"event": "tool_failed", "tool_call_id": ctx.tool_call_id}
            )
        span.set_attribute("sfmcp.outcome", outcome)

        error_code = denied.code.value if denied else failure_code
        try:
            await deps.auditor.record(
                ctx.bu or "global", _audit_event(ctx, deps, outcome, denied, error_code)
            )
        except Exception:
            log.exception(
                "audit write failed", extra={"event": "audit_failed", "tool_call_id": ctx.tool_call_id}
            )
            return _envelope(
                ctx, "error", None, ErrorCode.INTERNAL.value, "Audit unavailable; nothing was returned."
            )

    log.info(
        "tool call",
        extra={
            "event": "tool_call",
            "tool": ctx.tool_name[:128],
            "tool_call_id": ctx.tool_call_id,
            "key_id": ctx.principal.key_id if ctx.principal else None,
            "source_ip": ctx.principal.source_ip if ctx.principal else None,
            "outcome": outcome,
            "code": error_code,
            "rule_id": denied.rule_id if denied else ctx.allow_rule,
        },
    )
    if denied is not None:
        return _envelope(ctx, "denied", None, denied.code.value, denied.message)
    if outcome == "failed":
        return _envelope(ctx, "error", None, failure_code, failure_message)
    assert ctx.result is not None
    return _envelope(ctx, "ok", ctx.result.model_dump(mode="json"), None, None)
