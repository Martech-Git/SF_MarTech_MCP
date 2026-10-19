"""Seeded PII must never appear in logs, audit events or error output."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

from support import FakeClock, Stores

from sf_mcp.audit import Auditor
from sf_mcp.audit.chain import MemoryChainStore
from sf_mcp.audit.sink import StdoutAuditSink
from sf_mcp.auth.authenticator import ClientPrincipal
from sf_mcp.killswitch import CachedKillSwitches
from sf_mcp.logging_setup import RedactingJsonFormatter
from sf_mcp.pipeline.context import CallContext, PipelineDeps
from sf_mcp.pipeline.runner import run_tool_call
from sf_mcp.policy.loader import load_policy
from sf_mcp.ratelimit import RateLimiter
from sf_mcp.tools.registry import build_registry

SEEDS = ("jane.doe@example.com", "+1-555-0100", "4111111111111111", "Jane Doe", "90210")


def capture_logger() -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingJsonFormatter("proj"))
    logger = logging.getLogger("sf_mcp.test_redaction")
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    return logger, stream


def assert_clean(text: str) -> None:
    for seed in SEEDS:
        assert seed not in text, f"seeded value leaked: {seed}"


def test_formatter_drops_unlisted_fields_args_and_exception_messages() -> None:
    logger, stream = capture_logger()
    logger.info("lookup for %s", SEEDS[0], extra={"email": SEEDS[0], "phone": SEEDS[1], "tool": "health"})
    try:
        raise ValueError(f"row {SEEDS[3]} {SEEDS[2]} rejected")
    except ValueError:
        logger.exception("failed", extra={"code": "INTERNAL", "subscriber": SEEDS[4]})
    output = stream.getvalue()
    assert_clean(output)
    lines = [json.loads(line) for line in output.splitlines()]
    assert lines[0]["tool"] == "health"
    assert lines[1]["exception"]["type"] == "ValueError"


async def test_tool_call_with_seeded_arguments_leaks_nothing(
    policy_dir: Path, stores: Stores, clock: FakeClock
) -> None:
    bundle = load_policy(policy_dir)
    audit_stream = io.StringIO()
    deps = PipelineDeps(
        environment="local",
        registry=build_registry(),
        policy=lambda: bundle,
        killswitches=CachedKillSwitches(stores.switches, clock, 10),
        rate_limiter=RateLimiter(clock),
        auditor=Auditor(MemoryChainStore(), StdoutAuditSink(audit_stream)),
        clock=clock,
    )
    root_stream = io.StringIO()
    handler = logging.StreamHandler(root_stream)
    handler.setFormatter(RedactingJsonFormatter("proj"))
    pipeline_log = logging.getLogger("sf_mcp")
    pipeline_log.addHandler(handler)
    pipeline_log.setLevel(logging.DEBUG)
    try:
        ctx = CallContext(
            tool_call_id="c1",
            tool_name="health",
            raw_args={"email": SEEDS[0], "phone": SEEDS[1], "card": SEEDS[2], "name": SEEDS[3]},
            principal=ClientPrincipal(
                key_id="0123456789ab",
                client=bundle.clients["reader"],
                source_ip="1.1.1.1",
                asserted_user=None,
            ),
            started_monotonic=0.0,
            trace_id=None,
        )
        envelope = await run_tool_call(ctx, deps)
    finally:
        pipeline_log.removeHandler(handler)
    assert envelope["status"] == "denied"
    assert_clean(json.dumps(envelope))
    assert_clean(audit_stream.getvalue())
    assert_clean(root_stream.getvalue())
    audit_line = json.loads(audit_stream.getvalue().splitlines()[0])
    assert len(audit_line["input_hash"]) == 64
