"""Client API key format, generation and verification.

Format: sfmcp_<env>_<key_id>_<secret>
- env: local, dev, staging or prod
- key_id: 12 lowercase hex characters, public, used for lookup and audit
- secret: 32 random bytes, base64url without padding (43 characters)

The server stores only HMAC-SHA256(pepper, secret). The full key appears once, at issue.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

PREFIX = "sfmcp"
_KEY_RE = re.compile(r"^sfmcp_(local|dev|staging|prod)_([0-9a-f]{12})_([A-Za-z0-9_-]{43})$")
_KEY_ID_RE = re.compile(r"^[0-9a-f]{12}$")


@dataclass(frozen=True, slots=True)
class ParsedKey:
    environment: str
    key_id: str
    secret: str


def generate_key(environment: str) -> tuple[str, str, str]:
    """Return (key_id, secret, full_key)."""
    key_id = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    return key_id, secret, f"{PREFIX}_{environment}_{key_id}_{secret}"


def parse_key(raw: str) -> ParsedKey | None:
    match = _KEY_RE.fullmatch(raw)
    if match is None:
        return None
    return ParsedKey(environment=match.group(1), key_id=match.group(2), secret=match.group(3))


def is_key_id(value: str) -> bool:
    return _KEY_ID_RE.fullmatch(value) is not None


def hash_secret(pepper: bytes, secret: str) -> str:
    return hmac.new(pepper, secret.encode(), hashlib.sha256).hexdigest()


def secret_matches(pepper: bytes, secret: str, expected_hmac: str) -> bool:
    return hmac.compare_digest(hash_secret(pepper, secret), expected_hmac)
