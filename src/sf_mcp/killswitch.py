"""Kill switches: global off, read-only mode, per tool and per BU.

Stored in Firestore `config/kill_switches`, cached for a few seconds. If the store cannot be read,
the server treats every switch as engaged.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from sf_mcp.clock import Clock

log = logging.getLogger("sf_mcp.killswitch")


class KillSwitchState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    global_off: bool = False
    read_only: bool = False
    tools_off: frozenset[str] = Field(default_factory=frozenset)
    bus_off: frozenset[str] = Field(default_factory=frozenset)
    updated_at: datetime | None = None
    updated_by: str | None = None
    unreadable: bool = False

    @classmethod
    def fail_closed(cls) -> KillSwitchState:
        return cls(global_off=True, read_only=True, unreadable=True)


class KillSwitchStore(Protocol):
    async def read(self) -> KillSwitchState: ...

    async def write(self, state: KillSwitchState) -> None: ...


class MemoryKillSwitchStore:
    def __init__(self, initial: KillSwitchState | None = None) -> None:
        self._state = initial or KillSwitchState()

    async def read(self) -> KillSwitchState:
        return self._state

    async def write(self, state: KillSwitchState) -> None:
        self._state = state


class FirestoreKillSwitchStore:
    def __init__(self, client: Any) -> None:
        self._doc = client.collection("config").document("kill_switches")

    async def read(self) -> KillSwitchState:
        snapshot = await self._doc.get()
        if not snapshot.exists:
            return KillSwitchState()
        data = snapshot.to_dict() or {}
        data["tools_off"] = frozenset(data.get("tools_off", []))
        data["bus_off"] = frozenset(data.get("bus_off", []))
        return KillSwitchState.model_validate(data)

    async def write(self, state: KillSwitchState) -> None:
        data = state.model_dump(mode="python", exclude={"unreadable"})
        data["tools_off"] = sorted(state.tools_off)
        data["bus_off"] = sorted(state.bus_off)
        await self._doc.set(data)


class CachedKillSwitches:
    def __init__(self, store: KillSwitchStore, clock: Clock, ttl_seconds: float) -> None:
        self._store = store
        self._clock = clock
        self._ttl = ttl_seconds
        self._cached: tuple[float, KillSwitchState] | None = None

    async def current(self) -> KillSwitchState:
        now = self._clock.monotonic()
        if self._cached is not None and now - self._cached[0] < self._ttl:
            return self._cached[1]
        try:
            state = await self._store.read()
        except Exception:
            log.error(
                "kill switch store unreadable; failing closed", extra={"event": "killswitch_unreadable"}
            )
            state = KillSwitchState.fail_closed()
        self._cached = (now, state)
        return state

    async def update(self, state: KillSwitchState) -> None:
        await self._store.write(state)
        self._cached = None
