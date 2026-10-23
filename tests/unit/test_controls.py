"""Kill switches, rate limits and the audit hash chain."""

from __future__ import annotations

from datetime import UTC, datetime

from support import FakeClock

from sf_mcp.audit.chain import GENESIS, MemoryChainStore, verify_chain
from sf_mcp.audit.events import AdminAuditEvent
from sf_mcp.killswitch import CachedKillSwitches, KillSwitchState, MemoryKillSwitchStore
from sf_mcp.ratelimit import RateLimiter


class BrokenStore:
    async def read(self) -> KillSwitchState:
        raise RuntimeError("firestore down")

    async def write(self, state: KillSwitchState) -> None:
        raise RuntimeError("firestore down")


async def test_unreadable_kill_switch_store_fails_closed(clock: FakeClock) -> None:
    state = await CachedKillSwitches(BrokenStore(), clock, 10).current()
    assert state.global_off
    assert state.read_only
    assert state.unreadable


async def test_kill_switch_cache_expires(clock: FakeClock) -> None:
    store = MemoryKillSwitchStore()
    cached = CachedKillSwitches(store, clock, 10)
    assert not (await cached.current()).global_off
    await store.write(KillSwitchState(global_off=True))
    assert not (await cached.current()).global_off
    clock.advance(10)
    assert (await cached.current()).global_off


def test_rate_limiter_refills(clock: FakeClock) -> None:
    limiter = RateLimiter(clock)
    assert all(limiter.allow("k", 3) for _ in range(3))
    assert not limiter.allow("k", 3)
    clock.advance(20)
    assert limiter.allow("k", 3)
    assert not limiter.allow("k", 3)
    assert limiter.allow("other", 3)


def _event(n: int) -> AdminAuditEvent:
    return AdminAuditEvent(
        event_id=str(n),
        timestamp=datetime(2026, 10, 19, tzinfo=UTC),
        actor_email="a@example.com",
        action="key_issued",
        environment="local",
        target=f"key{n}",
        detail={},
    )


async def test_chain_links_and_verifies() -> None:
    store = MemoryChainStore()
    sealed = [await store.append("admin", _event(n)) for n in range(3)]
    assert sealed[0].chain is not None
    assert sealed[0].chain.prev_hash == GENESIS
    assert verify_chain(sealed) == []


async def test_chain_detects_tamper_and_gap() -> None:
    store = MemoryChainStore()
    sealed = [await store.append("admin", _event(n)) for n in range(3)]
    tampered = sealed[1].model_copy(update={"target": "other"})
    assert any("tampered" in p for p in verify_chain([sealed[0], tampered, sealed[2]]))
    assert any("gap" in p for p in verify_chain([sealed[0], sealed[2]]))
