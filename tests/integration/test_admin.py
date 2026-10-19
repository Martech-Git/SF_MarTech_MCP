"""Admin pages: IAP verification, platform admin check, CSRF, key issue and revoke, kill switches."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from support import ADMIN_EMAIL, FakeClock, Stores, fake_iap_verifier, make_settings

from sf_mcp.app import Overrides, create_app
from sf_mcp.auth.keys import parse_key

ADMIN = {"x-goog-iap-jwt-assertion": "iap-admin"}


@pytest.fixture
def client(policy_dir: Path, stores: Stores, clock: FakeClock) -> Iterator[TestClient]:
    app = create_app(
        make_settings(policy_dir),
        Overrides(
            clock=clock,
            key_store=stores.keys,
            kill_switch_store=stores.switches,
            chain_store=stores.chain,
            audit_sink=stores.audit,
            iap_verifier=fake_iap_verifier,
        ),
    )
    with TestClient(app) as test_client:
        yield test_client


def csrf_token(client: TestClient) -> str:
    page = client.get("/admin", headers=ADMIN)
    assert page.status_code == 200
    match = re.search(r"name=csrf value='([0-9]+\.[0-9a-f]{64})'", page.text)
    assert match is not None
    return match.group(1)


@pytest.mark.parametrize(
    "headers",
    [{}, {"x-goog-iap-jwt-assertion": "forged"}, {"x-goog-iap-jwt-assertion": "iap-wrong-issuer"}],
)
def test_admin_requires_valid_iap_assertion(client: TestClient, headers: dict[str, str]) -> None:
    assert client.get("/admin", headers=headers).status_code == 403


def test_admin_requires_platform_admin_in_policy(client: TestClient) -> None:
    assert client.get("/admin", headers={"x-goog-iap-jwt-assertion": "iap-other"}).status_code == 403
    page = client.get("/admin", headers=ADMIN)
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert ADMIN_EMAIL in page.text


def test_post_without_valid_csrf_is_rejected(client: TestClient, stores: Stores) -> None:
    response = client.post("/admin/keys/issue", headers=ADMIN, data={"client_id": "reader", "csrf": "1.abc"})
    assert response.status_code == 400
    assert stores.audit.events == []


async def test_issue_shows_key_once_then_revoke(client: TestClient, stores: Stores) -> None:
    token = csrf_token(client)
    issued = client.post("/admin/keys/issue", headers=ADMIN, data={"client_id": "reader", "csrf": token})
    assert issued.status_code == 200
    match = re.search(r"(sfmcp_local_[0-9a-f]{12}_[A-Za-z0-9_-]{43})", issued.text)
    assert match is not None
    full_key = match.group(1)
    parsed = parse_key(full_key)
    assert parsed is not None
    record = await stores.keys.get(parsed.key_id)
    assert record is not None
    assert record.status == "active"
    assert parsed.secret not in record.model_dump_json()
    assert full_key not in client.get("/admin", headers=ADMIN).text
    assert all(full_key not in event.model_dump_json() for event in stores.audit.events)

    revoked = client.post(
        "/admin/keys/revoke",
        headers=ADMIN,
        data={"key_id": parsed.key_id, "csrf": token},
        follow_redirects=False,
    )
    assert revoked.status_code == 303
    record = await stores.keys.get(parsed.key_id)
    assert record is not None
    assert record.status == "revoked"
    assert [e.action for e in stores.audit.events] == ["key_issued", "key_revoked"]


def test_key_limit_per_client(client: TestClient) -> None:
    token = csrf_token(client)
    for _ in range(2):
        assert (
            client.post(
                "/admin/keys/issue", headers=ADMIN, data={"client_id": "reader", "csrf": token}
            ).status_code
            == 200
        )
    third = client.post("/admin/keys/issue", headers=ADMIN, data={"client_id": "reader", "csrf": token})
    assert third.status_code == 400


def test_unknown_or_disabled_client_cannot_get_a_key(client: TestClient) -> None:
    token = csrf_token(client)
    for client_id in ("ghost", "disabled", "devonly"):
        response = client.post(
            "/admin/keys/issue", headers=ADMIN, data={"client_id": client_id, "csrf": token}
        )
        assert response.status_code == 400


async def test_kill_switch_toggle(client: TestClient, stores: Stores) -> None:
    token = csrf_token(client)
    response = client.post(
        "/admin/killswitch",
        headers=ADMIN,
        data={"field": "read_only", "value": "on", "csrf": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    state = await stores.switches.read()
    assert state.read_only
    assert state.updated_by == ADMIN_EMAIL
    bad = client.post(
        "/admin/killswitch", headers=ADMIN, data={"field": "tool:ghost", "value": "on", "csrf": token}
    )
    assert bad.status_code == 400
    assert stores.audit.events[-1].action == "kill_switch_changed"
