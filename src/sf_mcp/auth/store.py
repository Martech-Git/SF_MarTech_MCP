"""Key records. Firestore in deployed environments, memory in local runs and tests.

A record holds the key's HMAC and metadata only. Grants live in the policy bundle, keyed by client_id.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from sf_mcp.clock import Clock

KeyStatus = Literal["active", "revoked"]


class KeyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key_id: str
    client_id: str
    environment: str
    secret_hmac: str
    status: KeyStatus
    created_at: datetime
    expires_at: datetime
    issued_by: str
    revoked_at: datetime | None = None
    revoked_by: str | None = None

    def is_usable(self, now: datetime) -> bool:
        return self.status == "active" and now < self.expires_at


class KeyStore(Protocol):
    async def get(self, key_id: str) -> KeyRecord | None: ...

    async def put(self, record: KeyRecord) -> None: ...

    async def list_for_client(self, client_id: str) -> list[KeyRecord]: ...

    async def list_all(self) -> list[KeyRecord]: ...


class MemoryKeyStore:
    def __init__(self) -> None:
        self._records: dict[str, KeyRecord] = {}
        self._lock = asyncio.Lock()

    async def get(self, key_id: str) -> KeyRecord | None:
        return self._records.get(key_id)

    async def put(self, record: KeyRecord) -> None:
        async with self._lock:
            self._records[record.key_id] = record

    async def list_for_client(self, client_id: str) -> list[KeyRecord]:
        return [r for r in self._records.values() if r.client_id == client_id]

    async def list_all(self) -> list[KeyRecord]:
        return list(self._records.values())


class FirestoreKeyStore:
    """Collection `keys`, document id = key_id."""

    def __init__(self, client: Any, collection: str = "keys") -> None:
        self._collection = client.collection(collection)

    async def get(self, key_id: str) -> KeyRecord | None:
        snapshot = await self._collection.document(key_id).get()
        if not snapshot.exists:
            return None
        return KeyRecord.model_validate(snapshot.to_dict())

    async def put(self, record: KeyRecord) -> None:
        await self._collection.document(record.key_id).set(record.model_dump(mode="python"))

    async def list_for_client(self, client_id: str) -> list[KeyRecord]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self._collection.where(filter=FieldFilter("client_id", "==", client_id))
        return [KeyRecord.model_validate(doc.to_dict()) async for doc in query.stream()]

    async def list_all(self) -> list[KeyRecord]:
        return [KeyRecord.model_validate(doc.to_dict()) async for doc in self._collection.stream()]


class CachedKeyStore:
    """Caches lookups for a few seconds, so a revocation takes effect within `ttl_seconds`."""

    def __init__(self, inner: KeyStore, clock: Clock, ttl_seconds: float) -> None:
        self._inner = inner
        self._clock = clock
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, KeyRecord | None]] = {}

    async def get(self, key_id: str) -> KeyRecord | None:
        hit = self._cache.get(key_id)
        now = self._clock.monotonic()
        if hit is not None and now - hit[0] < self._ttl:
            return hit[1]
        record = await self._inner.get(key_id)
        self._cache[key_id] = (now, record)
        return record

    async def put(self, record: KeyRecord) -> None:
        await self._inner.put(record)
        self._cache.pop(record.key_id, None)

    async def list_for_client(self, client_id: str) -> list[KeyRecord]:
        return await self._inner.list_for_client(client_id)

    async def list_all(self) -> list[KeyRecord]:
        return await self._inner.list_all()
