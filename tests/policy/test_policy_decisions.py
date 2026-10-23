"""Decision table: (client, tool, BU, environment) and the expected verdict and rule."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from pydantic import BaseModel
from support import write_policy

from sf_mcp.policy.evaluator import authorize, visible_tools
from sf_mcp.policy.loader import load_policy
from sf_mcp.tools.health import SPEC as HEALTH
from sf_mcp.tools.registry import Role, Tier, ToolContext, ToolSpec


async def _noop(args: BaseModel, ctx: ToolContext) -> BaseModel:
    return args


# A BU-scoped T1 tool used only to exercise the evaluator. It is never registered.
WRITER = ToolSpec(
    name="health",
    title="test writer",
    tier=Tier.T1,
    min_role=Role.CONTENT_EDITOR,
    bu_scoped=True,
    backend="sfmc",
    input_model=BaseModel,
    handler=_noop,
    description="test",
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
)
SCOPED_VIEWER = dataclasses.replace(WRITER, tier=Tier.T0, min_role=Role.VIEWER)

EDITOR_CLIENTS = """
clients:
  - client_id: editor
    name: Editor
    owner: o@example.com
    environments: [local]
    allowed_sources: ["*"]
    max_tier: T1
    grants:
      - bu: sandbox
        roles: [content_editor]
      - bu: brand-b
        roles: [viewer]
  - client_id: capped
    name: Capped
    owner: o@example.com
    environments: [local]
    allowed_sources: ["*"]
    max_tier: T0
    grants:
      - bu: sandbox
        roles: [content_editor]
"""


@pytest.fixture
def bundle(tmp_path: Path):  # type: ignore[no-untyped-def]
    return load_policy(write_policy(tmp_path / "p", {"clients.yaml": EDITOR_CLIENTS}))


@pytest.mark.parametrize(
    ("client_id", "spec", "bu", "env", "allowed", "rule"),
    [
        ("editor", HEALTH, None, "local", True, "role.granted_any_bu"),
        ("editor", HEALTH, None, "prod", False, "client.environment"),
        ("editor", WRITER, "sandbox", "local", True, "role.granted"),
        ("editor", WRITER, "brand-b", "local", False, "role.missing"),
        ("editor", WRITER, None, "local", False, "bu.missing"),
        ("editor", WRITER, "nowhere", "local", False, "bu.unknown"),
        ("editor", SCOPED_VIEWER, "brand-b", "local", True, "role.granted"),
        ("capped", WRITER, "sandbox", "local", False, "client.max_tier"),
        ("capped", SCOPED_VIEWER, "brand-b", "local", False, "role.missing"),
    ],
)
def test_decision_table(bundle, client_id, spec, bu, env, allowed, rule) -> None:  # type: ignore[no-untyped-def]
    decision = authorize(bundle.clients[client_id], spec, bu, bundle, env)
    assert (decision.allowed, decision.rule_id) == (allowed, rule)


def test_disabled_tool_and_environment_rules(tmp_path: Path) -> None:
    disabled = "tools:\n  health:\n    enabled: false\n    environments: [local]\n"
    bundle = load_policy(write_policy(tmp_path / "a", {"tools.yaml": disabled}))
    assert authorize(bundle.clients["reader"], HEALTH, None, bundle, "local").rule_id == "tool.disabled"
    dev_only = "tools:\n  health:\n    enabled: true\n    environments: [dev]\n"
    bundle = load_policy(write_policy(tmp_path / "b", {"tools.yaml": dev_only}))
    assert authorize(bundle.clients["reader"], HEALTH, None, bundle, "local").rule_id == "tool.environment"


def test_client_without_grants_sees_zero_tools(policy_dir: Path) -> None:
    bundle = load_policy(policy_dir)
    registry = {"health": HEALTH}
    assert visible_tools(bundle.clients["nogrants"], registry, bundle, "local") == []
    assert visible_tools(bundle.clients["disabled"], registry, bundle, "local") == []
    assert [s.name for s in visible_tools(bundle.clients["reader"], registry, bundle, "local")] == ["health"]
