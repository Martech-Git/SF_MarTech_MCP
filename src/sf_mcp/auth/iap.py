"""Identity-Aware Proxy verification for the human pages (/admin now, /approvals in milestone 5).

IAP signs a JWT into `x-goog-iap-jwt-assertion`. The server verifies signature, issuer and audience
itself, so a request that reached the service without passing IAP gets nothing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import anyio

IAP_ISSUER = "https://cloud.google.com/iap"
IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"
IAP_HEADER = "x-goog-iap-jwt-assertion"


@dataclass(frozen=True, slots=True)
class HumanPrincipal:
    email: str
    subject: str


class IapFailure(Exception):
    pass


TokenVerifier = Callable[[str, str], Awaitable[Mapping[str, Any]]]


async def google_iap_verifier(token: str, audience: str) -> Mapping[str, Any]:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    def verify() -> Mapping[str, Any]:
        claims: Mapping[str, Any] = id_token.verify_token(
            token, google_requests.Request(), audience=audience, certs_url=IAP_CERTS_URL
        )
        return claims

    return await anyio.to_thread.run_sync(verify)


class IapAuthenticator:
    def __init__(
        self,
        *,
        audience: str | None,
        verifier: TokenVerifier = google_iap_verifier,
        dev_email: str | None = None,
    ) -> None:
        self._audience = audience
        self._verifier = verifier
        self._dev_email = dev_email

    async def authenticate(self, headers: Mapping[str, str]) -> HumanPrincipal:
        if self._dev_email is not None:
            # Settings allow this only when SFMCP_ENV=local.
            return HumanPrincipal(email=self._dev_email.lower(), subject="local-dev")
        if self._audience is None:
            raise IapFailure("no_audience_configured")
        token = headers.get(IAP_HEADER)
        if not token:
            raise IapFailure("missing_assertion")
        try:
            claims = await self._verifier(token, self._audience)
        except Exception as exc:
            raise IapFailure("invalid_assertion") from exc
        if claims.get("iss") != IAP_ISSUER:
            raise IapFailure("wrong_issuer")
        email = claims.get("email")
        subject = claims.get("sub")
        if not isinstance(email, str) or not isinstance(subject, str):
            raise IapFailure("missing_identity")
        return HumanPrincipal(email=email.lower(), subject=subject)
