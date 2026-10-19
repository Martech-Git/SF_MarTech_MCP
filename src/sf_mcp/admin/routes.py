"""Admin pages behind IAP: issue and revoke client keys, and set kill switches.

Only emails listed as platform_admins in policy/humans.yaml get in, after IAP verification.
Every change is audited in the "admin" chain. A new key is shown once and never logged.
"""

from __future__ import annotations

import html
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from sf_mcp.admin import csrf
from sf_mcp.audit import Auditor
from sf_mcp.audit.events import AdminAuditEvent
from sf_mcp.auth.iap import HumanPrincipal, IapAuthenticator, IapFailure
from sf_mcp.auth.keys import generate_key, hash_secret, is_key_id
from sf_mcp.auth.store import KeyRecord, KeyStore
from sf_mcp.clock import Clock
from sf_mcp.killswitch import CachedKillSwitches
from sf_mcp.policy.loader import PolicyBundle

log = logging.getLogger("sf_mcp.admin")

AdminAction = Literal["key_issued", "key_revoked", "kill_switch_changed"]

_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

_STYLE = (
    "body{font-family:system-ui,sans-serif;margin:24px;max-width:960px;color:#1a1a1a;background:#fff}"
    "h1{font-size:20px}h2{font-size:16px;margin-top:28px}table{border-collapse:collapse;width:100%}"
    "td,th{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left;font-size:14px}"
    "form{display:inline}button{padding:4px 10px}.on{color:#b00020;font-weight:600}"
    ".key{font-family:monospace;background:#f4f4f4;padding:12px;word-break:break-all}"
    ".note{color:#555;font-size:13px}"
)


@dataclass(frozen=True, slots=True)
class AdminDeps:
    environment: str
    iap: IapAuthenticator
    keys: KeyStore
    killswitches: CachedKillSwitches
    policy: Callable[[], PolicyBundle]
    auditor: Auditor
    clock: Clock
    pepper: bytes

    @property
    def csrf_key(self) -> bytes:
        return csrf.derive_key(self.pepper)


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    document = (
        f"<!doctype html><html lang=en><head><meta charset=utf-8><title>{_e(title)}</title>"
        f"<style>{_STYLE}</style></head><body>{body}</body></html>"
    )
    return HTMLResponse(document, status_code=status, headers=_HEADERS)


def _rejected(message: str) -> HTMLResponse:
    return _page("Rejected", f"<h1>{_e(message)}</h1><p><a href=/admin>Back to admin</a></p>", 400)


def build_admin_routes(deps: AdminDeps) -> list[Route]:
    async def admin_user(request: Request) -> HumanPrincipal | Response:
        headers = {k.lower(): v for k, v in request.headers.items()}
        try:
            human = await deps.iap.authenticate(headers)
        except IapFailure as failure:
            log.warning("admin iap failure", extra={"event": "admin_denied", "reason": str(failure)})
            return _page("Forbidden", "<h1>Forbidden</h1>", 403)
        admins = {str(email).lower() for email in deps.policy().humans.platform_admins}
        if human.email not in admins:
            log.warning(
                "admin not in policy", extra={"event": "admin_denied", "reason": "not_platform_admin"}
            )
            return _page("Forbidden", "<h1>Forbidden</h1>", 403)
        return human

    def _now_epoch() -> int:
        return int(deps.clock.now().timestamp())

    async def _checked_form(request: Request, human: HumanPrincipal) -> dict[str, str] | None:
        form = await request.form()
        fields = {k: v for k, v in form.items() if isinstance(v, str)}
        if not csrf.check(deps.csrf_key, human.email, fields.get("csrf", ""), _now_epoch()):
            return None
        return fields

    async def _audit(human: HumanPrincipal, action: AdminAction, target: str, detail: dict[str, str]) -> None:
        await deps.auditor.record(
            "admin",
            AdminAuditEvent(
                event_id=str(uuid.uuid4()),
                timestamp=deps.clock.now(),
                actor_email=human.email,
                action=action,
                environment=deps.environment,
                target=target,
                detail=detail,
            ),
        )

    async def dashboard(request: Request) -> Response:
        human = await admin_user(request)
        if isinstance(human, Response):
            return human
        bundle = deps.policy()
        switches = await deps.killswitches.current()
        token = _e(csrf.issue(deps.csrf_key, human.email, _now_epoch()))
        now = deps.clock.now()

        def toggle(field: str, label: str, engaged: bool) -> str:
            state = '<span class="on">ON</span>' if engaged else "off"
            value = "off" if engaged else "on"
            return (
                f"<tr><td>{_e(label)}</td><td>{state}</td><td><form method=post action=/admin/killswitch>"
                f"<input type=hidden name=csrf value='{token}'>"
                f"<input type=hidden name=field value='{_e(field)}'>"
                f"<input type=hidden name=value value='{value}'>"
                f"<button>Turn {value}</button></form></td></tr>"
            )

        rows = [
            toggle("global", "Global off", switches.global_off),
            toggle("read_only", "Read-only mode", switches.read_only),
        ]
        rows += [toggle(f"tool:{n}", f"Tool {n}", n in switches.tools_off) for n in sorted(bundle.tools)]
        rows += [
            toggle(f"bu:{alias}", f"Business unit {alias}", alias in switches.bus_off)
            for alias in sorted(bundle.business_units)
        ]

        blocks: list[str] = []
        for client_id, client in sorted(bundle.clients.items()):
            records = sorted(await deps.keys.list_for_client(client_id), key=lambda r: r.created_at)
            key_rows: list[str] = []
            for r in records:
                if r.environment != deps.environment:
                    continue
                expired = " (expired)" if r.status == "active" and not r.is_usable(now) else ""
                revoke = (
                    "<form method=post action=/admin/keys/revoke>"
                    f"<input type=hidden name=csrf value='{token}'>"
                    f"<input type=hidden name=key_id value='{_e(r.key_id)}'><button>Revoke</button></form>"
                    if r.status == "active"
                    else ""
                )
                key_rows.append(
                    f"<tr><td>{_e(r.key_id)}</td><td>{_e(r.status)}</td><td>{_e(r.created_at.date())}</td>"
                    f"<td>{_e(r.expires_at.date())}{expired}</td><td>{_e(r.issued_by)}</td><td>{revoke}</td></tr>"
                )
            grants = ", ".join(f"{g.bu}: {'/'.join(g.roles)}" for g in client.grants) or "no grants"
            blocks.append(
                f"<h2>{_e(client.name)} <span class=note>({_e(client_id)}; owner {_e(client.owner)}; "
                f"{_e(grants)})</span></h2><table><tr><th>Key id</th><th>Status</th><th>Created</th>"
                f"<th>Expires</th><th>Issued by</th><th></th></tr>{''.join(key_rows)}</table>"
                f"<p><form method=post action=/admin/keys/issue><input type=hidden name=csrf value='{token}'>"
                f"<input type=hidden name=client_id value='{_e(client_id)}'>"
                "<button>Issue key</button></form></p>"
            )

        body = (
            f"<h1>sf-mcp admin ({_e(deps.environment)})</h1>"
            f"<p class=note>Signed in as {_e(human.email)}. Policy version {_e(bundle.version)}.</p>"
            f"<h2>Kill switches</h2><table>{''.join(rows)}</table>"
            "<h2>Client keys</h2>"
            "<p class=note>Grants come from policy/clients.yaml and change by PR only.</p>" + "".join(blocks)
        )
        return _page("sf-mcp admin", body)

    async def issue_key(request: Request) -> Response:
        human = await admin_user(request)
        if isinstance(human, Response):
            return human
        fields = await _checked_form(request, human)
        if fields is None:
            return _rejected("Form expired. Reload the admin page.")
        bundle = deps.policy()
        client_id = fields.get("client_id", "")
        client = bundle.clients.get(client_id)
        if client is None or not client.enabled or deps.environment not in client.environments:
            return _rejected("Unknown or disabled client for this environment.")
        now = deps.clock.now()
        active = [
            r
            for r in await deps.keys.list_for_client(client_id)
            if r.environment == deps.environment and r.is_usable(now)
        ]
        if len(active) >= bundle.limits.keys_per_client:
            return _rejected("This client already holds the maximum number of active keys. Revoke one first.")
        key_id, secret, full_key = generate_key(deps.environment)
        record = KeyRecord(
            key_id=key_id,
            client_id=client_id,
            environment=deps.environment,
            secret_hmac=hash_secret(deps.pepper, secret),
            status="active",
            created_at=now,
            expires_at=now + timedelta(days=bundle.limits.key_max_days),
            issued_by=human.email,
        )
        await _audit(
            human, "key_issued", key_id, {"client_id": client_id, "expires_at": record.expires_at.isoformat()}
        )
        await deps.keys.put(record)
        body = (
            f"<h1>Key issued for {_e(client.name)}</h1>"
            "<p>Copy it now. It is shown once and the server cannot show it again.</p>"
            f"<p class=key>{_e(full_key)}</p>"
            f"<p class=note>Key id {_e(key_id)}, expires {_e(record.expires_at.date())}. "
            "Store it in the client's secret store or an environment variable, never in a repo.</p>"
            "<p><a href=/admin>Back to admin</a></p>"
        )
        return _page("Key issued", body)

    async def revoke_key(request: Request) -> Response:
        human = await admin_user(request)
        if isinstance(human, Response):
            return human
        fields = await _checked_form(request, human)
        if fields is None:
            return _rejected("Form expired. Reload the admin page.")
        key_id = fields.get("key_id", "")
        if not is_key_id(key_id):
            return _rejected("Unknown key.")
        record = await deps.keys.get(key_id)
        if record is None or record.environment != deps.environment:
            return _rejected("Unknown key.")
        if record.status == "revoked":
            return RedirectResponse("/admin", status_code=303)
        now = deps.clock.now()
        await _audit(human, "key_revoked", key_id, {"client_id": record.client_id})
        await deps.keys.put(
            record.model_copy(update={"status": "revoked", "revoked_at": now, "revoked_by": human.email})
        )
        return RedirectResponse("/admin", status_code=303)

    async def set_killswitch(request: Request) -> Response:
        human = await admin_user(request)
        if isinstance(human, Response):
            return human
        fields = await _checked_form(request, human)
        if fields is None:
            return _rejected("Form expired. Reload the admin page.")
        field = fields.get("field", "")
        value = fields.get("value", "")
        if value not in ("on", "off"):
            return _rejected("Unknown value.")
        engage = value == "on"
        bundle = deps.policy()
        state = await deps.killswitches.current()
        if state.unreadable:
            return _rejected("Kill switch store is unreadable; the server is already failing closed.")
        if field == "global":
            update: dict[str, object] = {"global_off": engage}
        elif field == "read_only":
            update = {"read_only": engage}
        elif field.startswith("tool:") and field[5:] in bundle.tools:
            name = field[5:]
            update = {"tools_off": state.tools_off | {name} if engage else state.tools_off - {name}}
        elif field.startswith("bu:") and field[3:] in bundle.business_units:
            alias = field[3:]
            update = {"bus_off": state.bus_off | {alias} if engage else state.bus_off - {alias}}
        else:
            return _rejected("Unknown switch.")
        update.update({"updated_at": deps.clock.now(), "updated_by": human.email})
        await _audit(human, "kill_switch_changed", field, {"value": value})
        await deps.killswitches.update(state.model_copy(update=update))
        log.warning(
            "kill switch changed", extra={"event": "kill_switch_changed", "reason": field, "status": value}
        )
        return RedirectResponse("/admin", status_code=303)

    return [
        Route("/admin", dashboard, methods=["GET"]),
        Route("/admin/keys/issue", issue_key, methods=["POST"]),
        Route("/admin/keys/revoke", revoke_key, methods=["POST"]),
        Route("/admin/killswitch", set_killswitch, methods=["POST"]),
    ]
