"""Tool registry. A tool exists only if it is listed in `build_registry` and has a policy entry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum
from importlib import resources
from typing import Any, Literal

import mcp_types as types
from pydantic import BaseModel


class Tier(IntEnum):
    T0 = 0
    T1 = 1
    T2 = 2
    T3 = 3


class Role(StrEnum):
    VIEWER = "viewer"
    CONTENT_EDITOR = "content_editor"
    DATA_OPERATOR = "data_operator"
    CAMPAIGN_OPERATOR = "campaign_operator"


Backend = Literal["none", "sfmc", "d360"]


@dataclass(frozen=True, slots=True)
class ToolContext:
    """What a handler may see. Handlers never reach logging, policy or secrets directly."""

    environment: str
    policy_version: str
    read_only: bool
    now: datetime


Handler = Callable[[Any, ToolContext], Awaitable[BaseModel]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    title: str
    tier: Tier
    min_role: Role
    bu_scoped: bool
    backend: Backend
    input_model: type[BaseModel]
    handler: Handler
    description: str
    read_only_hint: bool
    destructive_hint: bool
    idempotent_hint: bool

    def to_mcp(self) -> types.Tool:
        schema = self.input_model.model_json_schema()
        schema.setdefault("additionalProperties", False)
        return types.Tool(
            name=self.name,
            title=self.title,
            description=self.description,
            input_schema=schema,
            annotations=types.ToolAnnotations(
                title=self.title,
                read_only_hint=self.read_only_hint,
                destructive_hint=self.destructive_hint,
                idempotent_hint=self.idempotent_hint,
                open_world_hint=self.backend != "none",
            ),
        )


def load_description(tool_package: str) -> str:
    """Read the tool's description.md, which is the text the model sees."""
    text = resources.files(tool_package).joinpath("description.md").read_text(encoding="utf-8")
    return text.strip()


def build_registry() -> Mapping[str, ToolSpec]:
    """Every tool the server can expose. New tools are added here by PR, never discovered at runtime."""
    from sf_mcp.tools.health import SPEC as health_spec

    specs = [health_spec]
    registry: dict[str, ToolSpec] = {}
    for spec in specs:
        if spec.name in registry:
            raise ValueError(f"duplicate tool name {spec.name}")
        registry[spec.name] = spec
    return registry
