from __future__ import annotations

from pathlib import Path

import pytest
from support import PEPPER, FakeClock, Stores, issue_key

from sf_mcp.auth.authenticator import Authenticator, AuthFailure, Lockout, client_ip, sanitize_asserted_user
from sf_mcp.policy.loader import load_policy


def make_auth(
    policy_dir: Path, stores: Stores, clock: FakeClock, environment: str = "local"
) -> Authenticator:
    bundle = load_policy(policy_dir)
    return Authenticator(
        environment=environment,
        pepper=PEPPER,
        store=stores.keys,
        policy=lambda: bundle,
        clock=clock,
        lockout=Lockout(clock, 10, 300, 900),
        xff_index=-2,
    )


def headers(key: str, xff: str = "203.0.113.7, 34.1.1.1", **extra: str) -> dict[str, str]:
    return {"authorization": f"Bearer {key}", "x-forwarded-for": xff, **extra}


async def test_valid_key_authenticates(policy_dir: Path, stores: Stores, clock: FakeClock) -> None:
    key = await issue_key(stores.keys, clock, "reader")
    principal = await make_auth(policy_dir, stores, clock).authenticate(headers(key), "10.9.9.9")
    assert principal.client.client_id == "reader"
    assert principal.source_ip == "203.0.113.7"
    assert principal.asserted_user is None


async def test_asserted_user_is_recorded_when_well_formed(
    policy_dir: Path, stores: Stores, clock: FakeClock
) -> None:
    key = await issue_key(stores.keys, clock, "reader")
    auth = make_auth(policy_dir, stores, clock)
    principal = await auth.authenticate(headers(key, **{"x-acting-user": "Jane.Doe@Example.com"}), None)
    assert principal.asserted_user == "jane.doe@example.com"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a@b.co", "a@b.co"),
        ("not an email", None),
        ("a@b", None),
        ("x" * 300 + "@example.com", None),
        (None, None),
    ],
)
def test_asserted_user_sanitizing(value: str | None, expected: str | None) -> None:
    assert sanitize_asserted_user(value) == expected


async def expect_failure(auth: Authenticator, hdrs: dict[str, str], reason: str) -> None:
    with pytest.raises(AuthFailure) as info:
        await auth.authenticate(hdrs, None)
    assert info.value.reason == reason


async def test_missing_and_malformed_credentials(policy_dir: Path, stores: Stores, clock: FakeClock) -> None:
    auth = make_auth(policy_dir, stores, clock)
    await expect_failure(auth, {}, "missing_bearer")
    await expect_failure(auth, {"authorization": "Basic abc"}, "missing_bearer")
    await expect_failure(auth, {"authorization": "Bearer not-a-key"}, "malformed_key")


async def test_unknown_key_and_wrong_secret(policy_dir: Path, stores: Stores, clock: FakeClock) -> None:
    auth = make_auth(policy_dir, stores, clock)
    await expect_failure(auth, headers("sfmcp_local_0123456789ab_" + "a" * 43), "unknown_key")
    key = await issue_key(stores.keys, clock, "reader")
    tampered = key[:-1] + ("A" if key[-1] != "A" else "B")
    await expect_failure(auth, headers(tampered), "bad_secret")


async def test_revoked_and_expired_keys_fail(policy_dir: Path, stores: Stores, clock: FakeClock) -> None:
    auth = make_auth(policy_dir, stores, clock)
    revoked = await issue_key(stores.keys, clock, "reader", status="revoked")
    await expect_failure(auth, headers(revoked), "revoked")
    short = await issue_key(stores.keys, clock, "reader", days=1)
    clock.advance(2 * 86400)
    await expect_failure(auth, headers(short), "expired")


async def test_key_from_another_environment_fails(policy_dir: Path, stores: Stores, clock: FakeClock) -> None:
    auth = make_auth(policy_dir, stores, clock)
    key = await issue_key(stores.keys, clock, "reader", environment="dev")
    await expect_failure(auth, headers(key), "wrong_environment")


async def test_client_rules_from_policy(policy_dir: Path, stores: Stores, clock: FakeClock) -> None:
    auth = make_auth(policy_dir, stores, clock)
    await expect_failure(auth, headers(await issue_key(stores.keys, clock, "ghost")), "client_not_in_policy")
    await expect_failure(auth, headers(await issue_key(stores.keys, clock, "disabled")), "client_disabled")
    await expect_failure(auth, headers(await issue_key(stores.keys, clock, "devonly")), "client_environment")
    office = await issue_key(stores.keys, clock, "office")
    await expect_failure(auth, headers(office), "source_not_allowed")
    principal = await auth.authenticate(headers(office, xff="10.1.2.3, 34.1.1.1"), None)
    assert principal.client.client_id == "office"


async def test_lockout_blocks_source_after_ten_failures(
    policy_dir: Path, stores: Stores, clock: FakeClock
) -> None:
    auth = make_auth(policy_dir, stores, clock)
    good = await issue_key(stores.keys, clock, "reader")
    for _ in range(10):
        await expect_failure(auth, headers("sfmcp_local_0123456789ab_" + "a" * 43), "unknown_key")
    await expect_failure(auth, headers(good), "source_blocked")
    other_source = await auth.authenticate(headers(good, xff="198.51.100.4, 34.1.1.1"), None)
    assert other_source.client.client_id == "reader"
    clock.advance(901)
    assert (await auth.authenticate(headers(good), None)).client.client_id == "reader"


def test_client_ip_uses_load_balancer_position() -> None:
    assert client_ip({"x-forwarded-for": "1.1.1.1, 203.0.113.7, 34.1.1.1"}, None, -2) == "203.0.113.7"
    assert client_ip({}, "10.0.0.5", -2) == "10.0.0.5"
    assert client_ip({"x-forwarded-for": "34.1.1.1"}, "10.0.0.5", -2) == "10.0.0.5"
