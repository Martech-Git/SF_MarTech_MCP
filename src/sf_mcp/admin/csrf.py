"""CSRF tokens for admin forms: HMAC over the admin's email and issue time, valid for one hour."""

from __future__ import annotations

import hashlib
import hmac

TOKEN_TTL_SECONDS = 3600


def derive_key(pepper: bytes) -> bytes:
    return hmac.new(pepper, b"sfmcp-admin-csrf-v1", hashlib.sha256).digest()


def issue(key: bytes, email: str, now_epoch: int) -> str:
    mac = hmac.new(key, f"{email}|{now_epoch}".encode(), hashlib.sha256).hexdigest()
    return f"{now_epoch}.{mac}"


def check(key: bytes, email: str, token: str, now_epoch: int) -> bool:
    issued_raw, _, mac = token.partition(".")
    if not issued_raw.isdigit() or not mac:
        return False
    issued = int(issued_raw)
    if not 0 <= now_epoch - issued <= TOKEN_TTL_SECONDS:
        return False
    expected = hmac.new(key, f"{email}|{issued}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, mac)
