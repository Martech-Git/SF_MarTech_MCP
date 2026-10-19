"""Authorization decisions from the policy bundle. The model's claims never enter these functions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sf_mcp.policy.loader import PolicyBundle
from sf_mcp.policy.models import Client
from sf_mcp.tools.registry import Role, ToolSpec


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    rule_id: str


def roles_in_bu(client: Client, bu_alias: str) -> frozenset[Role]:
    for grant in client.grants:
        if grant.bu == bu_alias:
            held = set(grant.roles)
            # Every operator role includes viewer.
            held.add(Role.VIEWER)
            return frozenset(held)
    return frozenset()


def holds_role(client: Client, bu_alias: str, role: Role) -> bool:
    return role in roles_in_bu(client, bu_alias)


def _tool_open_to_client(client: Client, spec: ToolSpec, bundle: PolicyBundle, environment: str) -> Decision:
    if not client.enabled:
        return Decision(False, "client.disabled")
    if environment not in client.environments:
        return Decision(False, "client.environment")
    tool_policy = bundle.tools.get(spec.name)
    if tool_policy is None:
        return Decision(False, "tool.no_policy")
    if not tool_policy.enabled:
        return Decision(False, "tool.disabled")
    if environment not in tool_policy.environments:
        return Decision(False, "tool.environment")
    if client.max_tier < spec.tier:
        return Decision(False, "client.max_tier")
    return Decision(True, "tool.open")


def authorize(
    client: Client, spec: ToolSpec, bu_alias: str | None, bundle: PolicyBundle, environment: str
) -> Decision:
    """Decide whether this client may call this tool, on this BU, in this environment."""
    base = _tool_open_to_client(client, spec, bundle, environment)
    if not base.allowed:
        return base
    if spec.bu_scoped:
        if bu_alias is None:
            return Decision(False, "bu.missing")
        bu = bundle.business_units.get(bu_alias)
        if bu is None:
            return Decision(False, "bu.unknown")
        if environment not in bu.environments:
            return Decision(False, "bu.environment")
        if not holds_role(client, bu_alias, spec.min_role):
            return Decision(False, "role.missing")
        return Decision(True, "role.granted")
    # A tool without a BU needs the minimum role in at least one BU the client is granted.
    if any(holds_role(client, grant.bu, spec.min_role) for grant in client.grants):
        return Decision(True, "role.granted_any_bu")
    return Decision(False, "role.missing")


def visible_tools(
    client: Client, registry: Mapping[str, ToolSpec], bundle: PolicyBundle, environment: str
) -> list[ToolSpec]:
    """Tools this client may see in tools/list. Calls are still re-checked one by one."""
    visible: list[ToolSpec] = []
    for spec in registry.values():
        if not _tool_open_to_client(client, spec, bundle, environment).allowed:
            continue
        if any(holds_role(client, grant.bu, spec.min_role) for grant in client.grants):
            visible.append(spec)
    return sorted(visible, key=lambda s: s.name)
