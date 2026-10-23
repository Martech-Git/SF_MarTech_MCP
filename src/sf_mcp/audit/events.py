"""Audit event shapes. Fields are IDs, counts, hashes and decisions; there is no field for payload data."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Outcome = Literal["success", "denied", "failed", "verify_failed"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClientRef(_Frozen):
    key_id: str
    client_id: str
    owner: str


class PolicyRef(_Frozen):
    decision: Literal["allow", "deny"]
    rule_id: str
    version: str


class ChainRef(_Frozen):
    scope: str
    prev_hash: str
    hash: str


class ToolAuditEvent(_Frozen):
    event_type: Literal["sfmcp.audit.tool"] = "sfmcp.audit.tool"
    tool_call_id: str
    trace_id: str | None
    timestamp: datetime
    client: ClientRef
    asserted_user: str | None
    tool: str
    tier: str | None
    mode: str | None
    bu: str | None
    environment: str
    targets: list[str]
    input_hash: str
    output_hash: str | None
    counts: dict[str, int]
    policy: PolicyRef
    error_code: str | None
    outcome: Outcome
    duration_ms: int
    chain: ChainRef | None = None


class AdminAuditEvent(_Frozen):
    event_type: Literal["sfmcp.audit.admin"] = "sfmcp.audit.admin"
    event_id: str
    timestamp: datetime
    actor_email: str
    action: Literal["key_issued", "key_revoked", "kill_switch_changed"]
    environment: str
    target: str
    detail: dict[str, str]
    chain: ChainRef | None = None


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()
