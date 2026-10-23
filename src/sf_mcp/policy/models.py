"""Typed shape of the policy bundle in `policy/*.yaml`. Unknown fields fail validation."""

from __future__ import annotations

import ipaddress
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from sf_mcp.tools.registry import Role, Tier

Environment = Literal["local", "dev", "staging", "prod"]

_SLUG = r"^[a-z][a-z0-9_-]{1,62}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BusinessUnit(_Strict):
    alias: str = Field(pattern=_SLUG)
    mid: str = Field(pattern=r"^[0-9]{1,12}$")
    environments: list[Environment] = Field(min_length=1)
    description: str = ""


class Grant(_Strict):
    bu: str = Field(pattern=_SLUG)
    roles: list[Role] = Field(min_length=1)


class Client(_Strict):
    client_id: str = Field(pattern=_SLUG)
    name: str = Field(min_length=1, max_length=120)
    owner: EmailStr
    enabled: bool = True
    environments: list[Environment] = Field(min_length=1)
    allowed_sources: list[str] = Field(min_length=1)
    max_tier: Tier = Tier.T0
    pii_read: bool = False
    grants: list[Grant] = Field(default_factory=list)

    @field_validator("allowed_sources")
    @classmethod
    def _check_sources(cls, value: list[str]) -> list[str]:
        for source in value:
            if source == "*":
                continue
            ipaddress.ip_network(source, strict=False)
        return value

    @field_validator("pii_read")
    @classmethod
    def _no_pii_read_in_v1(cls, value: bool) -> bool:
        if value:
            raise ValueError("pii_read is not grantable in v1; masking is absolute (SPEC A10)")
        return value

    @field_validator("max_tier", mode="before")
    @classmethod
    def _parse_tier(cls, value: object) -> object:
        if isinstance(value, str) and value.upper() in Tier.__members__:
            return Tier[value.upper()]
        return value


class ClientsFile(_Strict):
    clients: list[Client]


class BusinessUnitsFile(_Strict):
    business_units: list[BusinessUnit]


class ToolPolicy(_Strict):
    enabled: bool
    environments: list[Environment] = Field(min_length=1)
    per_key_per_minute: int | None = Field(default=None, ge=1, le=600)


class ToolsFile(_Strict):
    tools: dict[str, ToolPolicy]


class Limits(_Strict):
    per_key_per_minute: int = Field(ge=1, le=600)
    per_bu_per_minute: int = Field(ge=1, le=2400)
    tenant_sync_per_minute: int = Field(ge=1, le=2400)
    page_default: int = Field(ge=1, le=200)
    page_max: int = Field(ge=1, le=200)
    sync_row_cap: int = Field(ge=1, le=500)
    auth_failures_before_block: int = Field(ge=1, le=100)
    auth_failure_window_seconds: int = Field(ge=10, le=3600)
    auth_block_seconds: int = Field(ge=10, le=86400)
    key_max_days: int = Field(ge=1, le=90)
    keys_per_client: int = Field(ge=1, le=2)

    @model_validator(mode="after")
    def _page_bounds(self) -> Limits:
        if self.page_max < self.page_default:
            raise ValueError("page_default must not exceed page_max")
        return self


class LimitsFile(_Strict):
    limits: Limits


class Humans(_Strict):
    platform_admins: list[EmailStr] = Field(default_factory=list)
    approvers: dict[str, list[EmailStr]] = Field(default_factory=dict)


class HumansFile(_Strict):
    humans: Humans
