"""Client authentication: API key, environment, policy client, source address and lockout.

Every failure returns the same generic 401 to the caller. The reason goes to the security log only.
"""

from __future__ import annotations

import ipaddress
import re
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sf_mcp.auth.keys import parse_key, secret_matches
from sf_mcp.auth.store import KeyStore
from sf_mcp.clock import Clock
from sf_mcp.policy.loader import PolicyBundle
from sf_mcp.policy.models import Client

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,180}\.[A-Za-z]{2,24}$")


@dataclass(frozen=True, slots=True)
class ClientPrincipal:
    key_id: str
    client: Client
    source_ip: str
    asserted_user: str | None


class AuthFailure(Exception):
    """Authentication failed. `reason` is for the security log, never for the caller."""

    def __init__(self, reason: str, key_id: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.key_id = key_id


class Lockout:
    """Counts failures per source and per key_id, and blocks either after too many.

    State is per instance. Cloud Armor rate limits sit in front as the shared control.
    """

    def __init__(self, clock: Clock, max_failures: int, window_seconds: int, block_seconds: int) -> None:
        self._clock = clock
        self._max = max_failures
        self._window = window_seconds
        self._block = block_seconds
        self._failures: dict[str, deque[float]] = {}
        self._blocked_until: dict[str, float] = {}

    def is_blocked(self, subject: str) -> bool:
        until = self._blocked_until.get(subject)
        if until is None:
            return False
        if self._clock.monotonic() < until:
            return True
        del self._blocked_until[subject]
        return False

    def record_failure(self, subject: str) -> None:
        now = self._clock.monotonic()
        window = self._failures.setdefault(subject, deque())
        window.append(now)
        while window and now - window[0] >= self._window:
            window.popleft()
        if len(window) >= self._max:
            self._blocked_until[subject] = now + self._block
            window.clear()


def client_ip(headers: Mapping[str, str], peer_host: str | None, xff_index: int) -> str:
    """Pick the caller's address from X-Forwarded-For as appended by the Google load balancer.

    The load balancer appends "<client-ip>, <lb-ip>", so the default index is -2. Anything the
    caller put earlier in the header is ignored.
    """
    forwarded = headers.get("x-forwarded-for", "")
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    if parts and -len(parts) <= xff_index < len(parts):
        return parts[xff_index]
    return peer_host or "unknown"


def source_allowed(client: Client, ip: str) -> bool:
    if "*" in client.allowed_sources:
        return True
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address in ipaddress.ip_network(cidr, strict=False) for cidr in client.allowed_sources)


def sanitize_asserted_user(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) <= 254 and _EMAIL_RE.fullmatch(value):
        return value.lower()
    return None


class Authenticator:
    def __init__(
        self,
        *,
        environment: str,
        pepper: bytes,
        store: KeyStore,
        policy: Callable[[], PolicyBundle],
        clock: Clock,
        lockout: Lockout,
        xff_index: int,
    ) -> None:
        self._environment = environment
        self._pepper = pepper
        self._store = store
        self._policy = policy
        self._clock = clock
        self._lockout = lockout
        self._xff_index = xff_index

    async def authenticate(self, headers: Mapping[str, str], peer_host: str | None) -> ClientPrincipal:
        ip = client_ip(headers, peer_host, self._xff_index)
        if self._lockout.is_blocked(f"ip:{ip}"):
            raise AuthFailure("source_blocked")

        authorization = headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            self._lockout.record_failure(f"ip:{ip}")
            raise AuthFailure("missing_bearer")

        parsed = parse_key(token.strip())
        if parsed is None:
            self._lockout.record_failure(f"ip:{ip}")
            raise AuthFailure("malformed_key")

        key_subject = f"key:{parsed.key_id}"
        if self._lockout.is_blocked(key_subject):
            raise AuthFailure("key_blocked", parsed.key_id)

        def fail(reason: str) -> AuthFailure:
            self._lockout.record_failure(f"ip:{ip}")
            self._lockout.record_failure(key_subject)
            return AuthFailure(reason, parsed.key_id)

        if parsed.environment != self._environment:
            raise fail("wrong_environment")

        record = await self._store.get(parsed.key_id)
        if record is None:
            raise fail("unknown_key")
        if not secret_matches(self._pepper, parsed.secret, record.secret_hmac):
            raise fail("bad_secret")
        if record.environment != self._environment:
            raise fail("record_environment")
        if record.status != "active":
            raise fail("revoked")
        if not record.is_usable(self._clock.now()):
            raise fail("expired")

        client = self._policy().clients.get(record.client_id)
        if client is None:
            raise fail("client_not_in_policy")
        if not client.enabled:
            raise fail("client_disabled")
        if self._environment not in client.environments:
            raise fail("client_environment")
        if not source_allowed(client, ip):
            raise fail("source_not_allowed")

        return ClientPrincipal(
            key_id=record.key_id,
            client=client,
            source_ip=ip,
            asserted_user=sanitize_asserted_user(headers.get("x-acting-user")),
        )
