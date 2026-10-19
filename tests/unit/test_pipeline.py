from __future__ import annotations

from pathlib import Path
from typing import Any

from support import FakeClock, Stores

from sf_mcp.audit import Auditor
from sf_mcp.auth.authenticator import ClientPrincipal
from sf_mcp.killswitch import CachedKillSwitches, KillSwitchState
from sf_mcp.pipeline.context import CallContext, PipelineDeps
from sf_mcp.pipeline.runner import run_tool_call
from sf_mcp.policy.loader import load_policy
from sf_mcp.ratelimit import RateLimiter
from sf_mcp.tools.registry import build_registry


class FailingChain:
    async def append(self, scope: str, event: Any) -> Any:
        raise RuntimeError("chain store down")


def make(policy_dir: Path, stores: Stores, clock: FakeClock, chain: Any = None) -> tuple[PipelineDeps, Any]:
    bundle = load_policy(policy_dir)
    deps = PipelineDeps(
        environment="local",
        registry=build_registry(),
        policy=lambda: bundle,
        killswitches=CachedKillSwitches(stores.switches, clock, 10),
        rate_limiter=RateLimiter(clock),
        auditor=Auditor(chain or stores.chain, stores.audit),
        clock=clock,
    )
    return deps, bundle


def call(
    bundle: Any, client_id: str | None, tool: str = "health", args: dict[str, Any] | None = None
) -> CallContext:
    principal = (
        ClientPrincipal(
            key_id="0123456789ab", client=bundle.clients[client_id], source_ip="1.1.1.1", asserted_user=None
        )
        if client_id
        else None
    )
    return CallContext(
        tool_call_id="call-1",
        tool_name=tool,
        raw_args=args or {},
        principal=principal,
        started_monotonic=0.0,
        trace_id=None,
    )


async def test_successful_call_returns_envelope_and_audits(
    policy_dir: Path, stores: Stores, clock: FakeClock
) -> None:
    deps, bundle = make(policy_dir, stores, clock)
    envelope = await run_tool_call(call(bundle, "reader"), deps)
    assert envelope["status"] == "ok"
    assert envelope["data"]["policy_version"] == bundle.version
    assert envelope["meta"]["tool_call_id"] == "call-1"
    [event] = stores.audit.events
    assert event.outcome == "success"
    assert event.policy.decision == "allow"
    assert event.chain is not None


async def expect_denied(deps: PipelineDeps, ctx: CallContext, code: str, rule: str, stores: Stores) -> None:
    envelope = await run_tool_call(ctx, deps)
    assert envelope["status"] == "denied"
    assert envelope["data"] is None
    assert envelope["error"]["code"] == code
    event = stores.audit.events[-1]
    assert event.outcome == "denied"
    assert event.policy.rule_id == rule


async def test_denials_cover_each_step(policy_dir: Path, stores: Stores, clock: FakeClock) -> None:
    deps, bundle = make(policy_dir, stores, clock)
    await expect_denied(deps, call(bundle, None), "UNAUTHENTICATED", "auth.missing", stores)
    await expect_denied(deps, call(bundle, "reader", tool="nope"), "NOT_FOUND", "tool.unknown", stores)
    await expect_denied(deps, call(bundle, "reader", args={"x": 1}), "VALIDATION", "schema.invalid", stores)
    await expect_denied(deps, call(bundle, "nogrants"), "PERMISSION", "role.missing", stores)


async def test_kill_switches(policy_dir: Path, stores: Stores, clock: FakeClock) -> None:
    deps, bundle = make(policy_dir, stores, clock)
    await stores.switches.write(KillSwitchState(tools_off=frozenset({"health"})))
    await expect_denied(deps, call(bundle, "reader"), "KILL_SWITCH", "kill.tool", stores)
    clock.advance(10)
    await stores.switches.write(KillSwitchState(global_off=True))
    await expect_denied(deps, call(bundle, "reader"), "KILL_SWITCH", "kill.global", stores)
    clock.advance(10)
    await stores.switches.write(KillSwitchState(read_only=True))
    assert (await run_tool_call(call(bundle, "reader"), deps))["status"] == "ok"


async def test_rate_limit_per_key_and_tool(policy_dir: Path, stores: Stores, clock: FakeClock) -> None:
    deps, bundle = make(policy_dir, stores, clock)
    statuses = [(await run_tool_call(call(bundle, "reader"), deps))["status"] for _ in range(31)]
    assert statuses.count("ok") == 30
    assert statuses[-1] == "denied"
    assert stores.audit.events[-1].policy.rule_id == "limit.key"


async def test_validation_message_never_echoes_values(
    policy_dir: Path, stores: Stores, clock: FakeClock
) -> None:
    deps, bundle = make(policy_dir, stores, clock)
    envelope = await run_tool_call(call(bundle, "reader", args={"email": "jane.doe@example.com"}), deps)
    assert "jane.doe" not in envelope["error"]["message"]
    assert "email" in envelope["error"]["message"]


async def test_audit_failure_withholds_the_result(policy_dir: Path, stores: Stores, clock: FakeClock) -> None:
    deps, bundle = make(policy_dir, stores, clock, chain=FailingChain())
    envelope = await run_tool_call(call(bundle, "reader"), deps)
    assert envelope["status"] == "error"
    assert envelope["data"] is None
    assert "Audit unavailable" in envelope["error"]["message"]
