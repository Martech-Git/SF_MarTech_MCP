"""Runtime settings read from the environment. Unsafe combinations stop the server at startup."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sf_mcp.errors import ConfigError

Environment = Literal["local", "dev", "staging", "prod"]
StoreBackend = Literal["memory", "firestore"]
OtelExporter = Literal["none", "gcp"]

_ENVIRONMENTS: tuple[Environment, ...] = ("local", "dev", "staging", "prod")
_MIN_PEPPER_BYTES = 32


@dataclass(frozen=True, slots=True)
class Settings:
    environment: Environment
    store_backend: StoreBackend
    gcp_project: str | None
    firestore_database: str
    policy_dir: Path
    key_pepper: bytes
    iap_audience_admin: str | None
    dev_admin_email: str | None
    xff_client_index: int
    otel_exporter: OtelExporter
    allowed_hosts: tuple[str, ...]
    cache_seconds: float
    port: int
    log_level: str


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value


def _load_pepper(env: Mapping[str, str], environment: Environment) -> bytes:
    path = env.get("SFMCP_KEY_PEPPER_FILE", "").strip()
    if path:
        pepper = Path(path).read_bytes().strip()
    elif environment == "local":
        pepper = env.get("SFMCP_KEY_PEPPER", "").encode()
    else:
        raise ConfigError("SFMCP_KEY_PEPPER_FILE is required outside local; mount the secret as a file")
    if len(pepper) < _MIN_PEPPER_BYTES:
        raise ConfigError(f"key pepper must be at least {_MIN_PEPPER_BYTES} bytes")
    return pepper


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env

    raw_environment = _required(env, "SFMCP_ENV")
    if raw_environment not in _ENVIRONMENTS:
        raise ConfigError(f"SFMCP_ENV must be one of {', '.join(_ENVIRONMENTS)}")
    environment: Environment = raw_environment

    raw_store = env.get("SFMCP_STORE", "memory" if environment == "local" else "firestore")
    if raw_store not in ("memory", "firestore"):
        raise ConfigError("SFMCP_STORE must be memory or firestore")
    store_backend: StoreBackend = raw_store  # type: ignore[assignment]
    if store_backend == "memory" and environment != "local":
        raise ConfigError("the memory store is allowed in local only")

    gcp_project = env.get("SFMCP_GCP_PROJECT", "").strip() or None
    if store_backend == "firestore" and gcp_project is None:
        raise ConfigError("SFMCP_GCP_PROJECT is required with the firestore store")

    iap_audience_admin = env.get("SFMCP_IAP_AUDIENCE_ADMIN", "").strip() or None
    dev_admin_email = env.get("SFMCP_DEV_ADMIN_EMAIL", "").strip() or None
    if dev_admin_email is not None and environment != "local":
        raise ConfigError("SFMCP_DEV_ADMIN_EMAIL bypasses IAP and is allowed in local only")
    if environment != "local" and iap_audience_admin is None:
        raise ConfigError("SFMCP_IAP_AUDIENCE_ADMIN is required outside local")

    raw_exporter = env.get("SFMCP_OTEL_EXPORTER", "none")
    if raw_exporter not in ("none", "gcp"):
        raise ConfigError("SFMCP_OTEL_EXPORTER must be none or gcp")
    otel_exporter: OtelExporter = raw_exporter  # type: ignore[assignment]

    try:
        xff_client_index = int(env.get("SFMCP_XFF_CLIENT_INDEX", "-2"))
        cache_seconds = float(env.get("SFMCP_CACHE_SECONDS", "10"))
        port = int(env.get("PORT", "8080"))
    except ValueError as exc:
        raise ConfigError("SFMCP_XFF_CLIENT_INDEX, SFMCP_CACHE_SECONDS and PORT must be numbers") from exc
    if not 0 < cache_seconds <= 10:
        raise ConfigError("SFMCP_CACHE_SECONDS must be above 0 and at most 10")

    allowed_hosts = tuple(h.strip() for h in env.get("SFMCP_ALLOWED_HOSTS", "").split(",") if h.strip())

    return Settings(
        environment=environment,
        store_backend=store_backend,
        gcp_project=gcp_project,
        firestore_database=env.get("SFMCP_FIRESTORE_DATABASE", "sf-mcp"),
        policy_dir=Path(env.get("SFMCP_POLICY_DIR", "policy")),
        key_pepper=_load_pepper(env, environment),
        iap_audience_admin=iap_audience_admin,
        dev_admin_email=dev_admin_email,
        xff_client_index=xff_client_index,
        otel_exporter=otel_exporter,
        allowed_hosts=allowed_hosts,
        cache_seconds=cache_seconds,
        port=port,
        log_level=env.get("SFMCP_LOG_LEVEL", "INFO").upper(),
    )
