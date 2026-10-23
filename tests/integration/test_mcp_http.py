"""End to end over real HTTP: uvicorn serving the app, the official MCP client calling it."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from support import FakeClock, Stores, fake_iap_verifier, issue_key, make_settings

from sf_mcp.app import Overrides, create_app
from sf_mcp.killswitch import KillSwitchState


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def server(policy_dir: Path, stores: Stores, clock: FakeClock) -> Iterator[str]:
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
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False)
    uv = uvicorn.Server(config)
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not uv.started:
        if deadline < time.monotonic():
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    uv.should_exit = True
    thread.join(timeout=10)


def client_for(base: str, key: str) -> Client:
    http = create_mcp_http_client(headers={"Authorization": f"Bearer {key}"})
    return Client(streamable_http_client(f"{base}/mcp", http_client=http))


async def test_granted_key_lists_and_calls_health(server: str, stores: Stores, clock: FakeClock) -> None:
    key = await issue_key(stores.keys, clock, "reader")
    async with client_for(server, key) as client:
        tools = await client.list_tools()
        assert [t.name for t in tools.tools] == ["health"]
        result = await client.call_tool("health", {})
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["status"] == "ok"
    assert result.structured_content["data"]["environment"] == "local"
    assert stores.audit.events[-1].client.client_id == "reader"


async def test_key_without_grants_sees_zero_tools(server: str, stores: Stores, clock: FakeClock) -> None:
    key = await issue_key(stores.keys, clock, "nogrants")
    async with client_for(server, key) as client:
        assert (await client.list_tools()).tools == []
        result = await client.call_tool("health", {})
    assert result.is_error is True
    assert result.structured_content is not None
    assert result.structured_content["error"]["code"] == "PERMISSION"


async def test_bad_revoked_and_expired_keys_get_401(server: str, stores: Stores, clock: FakeClock) -> None:
    revoked = await issue_key(stores.keys, clock, "reader", status="revoked")
    expired = await issue_key(stores.keys, clock, "reader", days=1)
    clock.advance(2 * 86400)
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    async with httpx.AsyncClient() as http:
        attempts: list[dict[str, str]] = [
            {},
            {"Authorization": "Basic abc"},
            {"Authorization": "Bearer garbage"},
            {"Authorization": "Bearer sfmcp_local_0123456789ab_" + "a" * 43},
            {"Authorization": f"Bearer {revoked}"},
            {"Authorization": f"Bearer {expired}"},
        ]
        for headers in attempts:
            response = await http.post(f"{server}/mcp", json=body, headers=headers)
            assert response.status_code == 401
            assert response.json() == {"error": "unauthorized"}


async def test_global_kill_switch_empties_tool_list(server: str, stores: Stores, clock: FakeClock) -> None:
    key = await issue_key(stores.keys, clock, "reader")
    await stores.switches.write(KillSwitchState(global_off=True))
    async with client_for(server, key) as client:
        assert (await client.list_tools()).tools == []
        result = await client.call_tool("health", {})
    assert result.structured_content is not None
    assert result.structured_content["error"]["code"] == "KILL_SWITCH"


async def test_healthz_needs_no_key(server: str) -> None:
    async with httpx.AsyncClient() as http:
        response = await http.get(f"{server}/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
