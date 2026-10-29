"""Application assembly: settings, policy, stores, pipeline, MCP transport and admin pages."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from sf_mcp import SERVICE_NAME, __version__
from sf_mcp.admin.routes import AdminDeps, build_admin_routes
from sf_mcp.audit import Auditor
from sf_mcp.audit.chain import ChainStore, FirestoreChainStore, MemoryChainStore
from sf_mcp.audit.sink import AuditSink, StdoutAuditSink
from sf_mcp.auth.authenticator import Authenticator, Lockout
from sf_mcp.auth.iap import IapAuthenticator, TokenVerifier, google_iap_verifier
from sf_mcp.auth.middleware import MCPAuthApp
from sf_mcp.auth.store import CachedKeyStore, FirestoreKeyStore, KeyStore, MemoryKeyStore
from sf_mcp.clock import Clock, SystemClock
from sf_mcp.config import Settings
from sf_mcp.killswitch import (
    CachedKillSwitches,
    FirestoreKillSwitchStore,
    KillSwitchStore,
    MemoryKillSwitchStore,
)
from sf_mcp.mcp_server import build_mcp_server
from sf_mcp.pipeline.context import PipelineDeps
from sf_mcp.policy.loader import PolicyBundle, check_alignment, load_policy
from sf_mcp.ratelimit import RateLimiter
from sf_mcp.tools.registry import build_registry


@dataclass(slots=True)
class Overrides:
    """Test seams. Production leaves every field as None."""

    clock: Clock | None = None
    key_store: KeyStore | None = None
    kill_switch_store: KillSwitchStore | None = None
    chain_store: ChainStore | None = None
    audit_sink: AuditSink | None = None
    iap_verifier: TokenVerifier | None = None


def _firestore_client(settings: Settings) -> Any:
    from google.cloud import firestore

    return firestore.AsyncClient(project=settings.gcp_project, database=settings.firestore_database)


def create_app(settings: Settings, overrides: Overrides | None = None) -> Starlette:
    overrides = overrides or Overrides()
    clock = overrides.clock or SystemClock()

    registry = build_registry()
    bundle = load_policy(settings.policy_dir)
    check_alignment(bundle, registry)
    policy: Callable[[], PolicyBundle] = lambda: bundle  # noqa: E731

    firestore_client = _firestore_client(settings) if settings.store_backend == "firestore" else None

    def pick(override: Any, memory: Callable[[], Any], firestore: Callable[[Any], Any]) -> Any:
        if override is not None:
            return override
        return memory() if firestore_client is None else firestore(firestore_client)

    key_store: KeyStore = pick(overrides.key_store, MemoryKeyStore, FirestoreKeyStore)
    kill_store: KillSwitchStore = pick(
        overrides.kill_switch_store, MemoryKillSwitchStore, FirestoreKillSwitchStore
    )
    chain_store: ChainStore = pick(overrides.chain_store, MemoryChainStore, FirestoreChainStore)
    auditor = Auditor(chain_store, overrides.audit_sink or StdoutAuditSink())
    killswitches = CachedKillSwitches(kill_store, clock, settings.cache_seconds)

    limits = bundle.limits
    authenticator = Authenticator(
        environment=settings.environment,
        pepper=settings.key_pepper,
        store=CachedKeyStore(key_store, clock, settings.cache_seconds),
        policy=policy,
        clock=clock,
        lockout=Lockout(
            clock,
            limits.auth_failures_before_block,
            limits.auth_failure_window_seconds,
            limits.auth_block_seconds,
        ),
        xff_index=settings.xff_client_index,
    )

    deps = PipelineDeps(
        environment=settings.environment,
        registry=registry,
        policy=policy,
        killswitches=killswitches,
        rate_limiter=RateLimiter(clock),
        auditor=auditor,
        clock=clock,
    )
    mcp_server = build_mcp_server(deps)
    security = (
        TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=list(settings.allowed_hosts)
        )
        if settings.allowed_hosts
        else TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server, stateless=True, json_response=True, security_settings=security
    )
    mcp_endpoint = MCPAuthApp(StreamableHTTPASGIApp(session_manager), authenticator)

    admin_routes = build_admin_routes(
        AdminDeps(
            environment=settings.environment,
            iap=IapAuthenticator(
                audience=settings.iap_audience_admin,
                verifier=overrides.iap_verifier or google_iap_verifier,
                dev_email=settings.dev_admin_email,
            ),
            keys=key_store,
            killswitches=killswitches,
            policy=policy,
            auditor=auditor,
            clock=clock,
            pepper=settings.key_pepper,
        )
    )

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "service": SERVICE_NAME,
                "version": __version__,
                "policy_version": bundle.version,
            },
            headers={"Cache-Control": "no-store"},
        )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    import os

    service_role = os.environ.get("SFMCP_SERVICE_ROLE", "both").lower()
    if service_role not in {"both", "mcp", "admin"}:
        raise ValueError("Invalid SFMCP_SERVICE_ROLE")

    routes = [
        Route("/health", healthz, methods=["GET"]),
        Route("/healthz", healthz, methods=["GET"]),
    ]

    if service_role in {"both", "mcp"}:
        routes.append(
            Route("/mcp", endpoint=mcp_endpoint, methods=["GET", "POST", "DELETE"])
        )

    if service_role in {"both", "admin"}:
        routes.extend(admin_routes)

    return Starlette(
        routes=routes,
        lifespan=lifespan,
    )
