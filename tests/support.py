from __future__ import annotations

import textwrap
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sf_mcp.audit.chain import MemoryChainStore
from sf_mcp.audit.sink import MemoryAuditSink
from sf_mcp.auth.iap import IAP_ISSUER
from sf_mcp.auth.keys import generate_key, hash_secret
from sf_mcp.auth.store import KeyRecord, MemoryKeyStore
from sf_mcp.config import Settings
from sf_mcp.killswitch import MemoryKillSwitchStore

PEPPER = b"p" * 48
ADMIN_EMAIL = "admin@example.com"
OTHER_EMAIL = "someone@example.com"
IAP_AUDIENCE = "/projects/1/global/backendServices/2"


class FakeClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
        self._mono = 1000.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._mono += seconds


POLICY = {
    "business_units.yaml": """
        business_units:
          - alias: sandbox
            mid: "123"
            environments: [local, dev]
          - alias: brand-b
            mid: "456"
            environments: [local]
        """,
    "clients.yaml": """
        clients:
          - client_id: reader
            name: Reader
            owner: owner@example.com
            environments: [local]
            allowed_sources: ["*"]
            grants:
              - bu: sandbox
                roles: [viewer]
          - client_id: nogrants
            name: No grants
            owner: owner@example.com
            environments: [local]
            allowed_sources: ["*"]
          - client_id: disabled
            name: Disabled
            owner: owner@example.com
            enabled: false
            environments: [local]
            allowed_sources: ["*"]
            grants:
              - bu: sandbox
                roles: [viewer]
          - client_id: office
            name: Office only
            owner: owner@example.com
            environments: [local]
            allowed_sources: ["10.0.0.0/8"]
            grants:
              - bu: sandbox
                roles: [viewer]
          - client_id: devonly
            name: Dev only
            owner: owner@example.com
            environments: [dev]
            allowed_sources: ["*"]
            grants:
              - bu: sandbox
                roles: [viewer]
        """,
    "tools.yaml": """
        tools:
          health:
            enabled: true
            environments: [local, dev, staging, prod]
            per_key_per_minute: 30
        """,
    "limits.yaml": """
        limits:
          per_key_per_minute: 60
          per_bu_per_minute: 300
          tenant_sync_per_minute: 2000
          page_default: 50
          page_max: 200
          sync_row_cap: 500
          auth_failures_before_block: 10
          auth_failure_window_seconds: 300
          auth_block_seconds: 900
          key_max_days: 90
          keys_per_client: 2
        """,
    "humans.yaml": f"""
        humans:
          platform_admins: [{ADMIN_EMAIL}]
          approvers: {{}}
        """,
}


def write_policy(directory: Path, overrides: Mapping[str, str] | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    files = dict(POLICY)
    files.update(overrides or {})
    for name, content in files.items():
        (directory / name).write_text(textwrap.dedent(content).lstrip())
    return directory


def make_settings(policy_dir: Path, **changes: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "local",
        "store_backend": "memory",
        "gcp_project": None,
        "firestore_database": "sf-mcp",
        "policy_dir": policy_dir,
        "key_pepper": PEPPER,
        "iap_audience_admin": IAP_AUDIENCE,
        "dev_admin_email": None,
        "xff_client_index": -2,
        "otel_exporter": "none",
        "allowed_hosts": (),
        "cache_seconds": 10.0,
        "port": 8080,
        "log_level": "INFO",
    }
    values.update(changes)
    return Settings(**values)


async def fake_iap_verifier(token: str, audience: str) -> Mapping[str, Any]:
    if audience != IAP_AUDIENCE:
        raise ValueError("wrong audience")
    if token == "iap-admin":
        return {"iss": IAP_ISSUER, "email": ADMIN_EMAIL, "sub": "1"}
    if token == "iap-other":
        return {"iss": IAP_ISSUER, "email": OTHER_EMAIL, "sub": "2"}
    if token == "iap-wrong-issuer":
        return {"iss": "https://accounts.google.com", "email": ADMIN_EMAIL, "sub": "1"}
    raise ValueError("bad token")


@dataclass
class Stores:
    keys: MemoryKeyStore = field(default_factory=MemoryKeyStore)
    switches: MemoryKillSwitchStore = field(default_factory=MemoryKillSwitchStore)
    chain: MemoryChainStore = field(default_factory=MemoryChainStore)
    audit: MemoryAuditSink = field(default_factory=MemoryAuditSink)


async def issue_key(
    store: MemoryKeyStore,
    clock: FakeClock,
    client_id: str,
    *,
    environment: str = "local",
    status: str = "active",
    days: int = 90,
) -> str:
    key_id, secret, full_key = generate_key(environment)
    await store.put(
        KeyRecord(
            key_id=key_id,
            client_id=client_id,
            environment=environment,
            secret_hmac=hash_secret(PEPPER, secret),
            status=status,  # type: ignore[arg-type]
            created_at=clock.now(),
            expires_at=clock.now() + timedelta(days=days),
            issued_by=ADMIN_EMAIL,
        )
    )
    return full_key
