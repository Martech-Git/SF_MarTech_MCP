"""Load and cross-check the policy bundle. Any problem stops the server from starting."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from sf_mcp.errors import PolicyError
from sf_mcp.policy.models import (
    BusinessUnit,
    BusinessUnitsFile,
    Client,
    ClientsFile,
    Humans,
    HumansFile,
    Limits,
    LimitsFile,
    ToolPolicy,
    ToolsFile,
)
from sf_mcp.tools.registry import ToolSpec

POLICY_FILES = ("business_units.yaml", "clients.yaml", "tools.yaml", "limits.yaml", "humans.yaml")


@dataclass(frozen=True, slots=True)
class PolicyBundle:
    version: str
    business_units: Mapping[str, BusinessUnit]
    clients: Mapping[str, Client]
    tools: Mapping[str, ToolPolicy]
    limits: Limits
    humans: Humans


def _read[M: BaseModel](path: Path, model: type[M]) -> tuple[M, bytes]:
    if not path.is_file():
        raise PolicyError(f"missing policy file {path.name}")
    raw = path.read_bytes()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PolicyError(f"{path.name} is not valid YAML") from exc
    try:
        return model.model_validate(data), raw
    except ValidationError as exc:
        raise PolicyError(f"{path.name} failed validation: {exc.error_count()} error(s)\n{exc}") from exc


def load_policy(policy_dir: Path) -> PolicyBundle:
    bus_file, bus_raw = _read(policy_dir / "business_units.yaml", BusinessUnitsFile)
    clients_file, clients_raw = _read(policy_dir / "clients.yaml", ClientsFile)
    tools_file, tools_raw = _read(policy_dir / "tools.yaml", ToolsFile)
    limits_file, limits_raw = _read(policy_dir / "limits.yaml", LimitsFile)
    humans_file, humans_raw = _read(policy_dir / "humans.yaml", HumansFile)

    business_units: dict[str, BusinessUnit] = {}
    for bu in bus_file.business_units:
        if bu.alias in business_units:
            raise PolicyError(f"duplicate business unit alias {bu.alias}")
        business_units[bu.alias] = bu

    clients: dict[str, Client] = {}
    for client in clients_file.clients:
        if client.client_id in clients:
            raise PolicyError(f"duplicate client_id {client.client_id}")
        seen_bus: set[str] = set()
        for grant in client.grants:
            if grant.bu not in business_units:
                raise PolicyError(
                    f"client {client.client_id} has a grant on unknown business unit {grant.bu}"
                )
            if grant.bu in seen_bus:
                raise PolicyError(f"client {client.client_id} has two grants on {grant.bu}; merge them")
            seen_bus.add(grant.bu)
        clients[client.client_id] = client

    for bu_alias, emails in humans_file.humans.approvers.items():
        if bu_alias not in business_units:
            raise PolicyError(f"approvers listed for unknown business unit {bu_alias}")
        if not emails:
            raise PolicyError(f"approver list for {bu_alias} is empty; remove the entry instead")

    digest = hashlib.sha256()
    for name, raw in zip(
        POLICY_FILES, (bus_raw, clients_raw, tools_raw, limits_raw, humans_raw), strict=True
    ):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")

    return PolicyBundle(
        version=digest.hexdigest()[:12],
        business_units=business_units,
        clients=clients,
        tools=dict(tools_file.tools),
        limits=limits_file.limits,
        humans=humans_file.humans,
    )


def check_alignment(bundle: PolicyBundle, registry: Mapping[str, ToolSpec]) -> None:
    """Every registered tool needs a policy entry, and every policy entry needs a registered tool."""
    missing = sorted(set(registry) - set(bundle.tools))
    unknown = sorted(set(bundle.tools) - set(registry))
    if missing:
        raise PolicyError(f"tools without a policy entry: {', '.join(missing)}")
    if unknown:
        raise PolicyError(f"policy entries for unknown tools: {', '.join(unknown)}")
