"""Hash chain per scope (a BU alias, "global" or "admin").

Each event carries the previous event's hash. Chain heads live in Firestore `audit_chain_heads`,
advanced inside a transaction so concurrent instances cannot fork a chain.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterable
from typing import Any, Protocol

from sf_mcp.audit.events import AdminAuditEvent, ChainRef, ToolAuditEvent, canonical_json

GENESIS = "0" * 64

AuditEvent = ToolAuditEvent | AdminAuditEvent


def event_hash(event_without_chain: dict[str, Any], prev_hash: str) -> str:
    digest = hashlib.sha256()
    digest.update(prev_hash.encode())
    digest.update(canonical_json(event_without_chain))
    return digest.hexdigest()


def _body(event: AuditEvent) -> dict[str, Any]:
    return event.model_dump(mode="json", exclude={"chain"})


def seal(event: AuditEvent, scope: str, prev_hash: str) -> AuditEvent:
    chain = ChainRef(scope=scope, prev_hash=prev_hash, hash=event_hash(_body(event), prev_hash))
    return event.model_copy(update={"chain": chain})


def verify_chain(events: Iterable[AuditEvent]) -> list[str]:
    """Return problems found, empty when every scope's chain is intact and in order."""
    problems: list[str] = []
    heads: dict[str, str] = {}
    for event in events:
        if event.chain is None:
            problems.append("event without chain")
            continue
        expected_prev = heads.get(event.chain.scope, GENESIS)
        if event.chain.prev_hash != expected_prev:
            problems.append(f"gap or reorder in scope {event.chain.scope}")
        if event_hash(_body(event), event.chain.prev_hash) != event.chain.hash:
            problems.append(f"tampered event in scope {event.chain.scope}")
        heads[event.chain.scope] = event.chain.hash
    return problems


class ChainStore(Protocol):
    async def append(self, scope: str, event: AuditEvent) -> AuditEvent: ...


class MemoryChainStore:
    def __init__(self) -> None:
        self._heads: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def append(self, scope: str, event: AuditEvent) -> AuditEvent:
        async with self._lock:
            sealed = seal(event, scope, self._heads.get(scope, GENESIS))
            assert sealed.chain is not None
            self._heads[scope] = sealed.chain.hash
            return sealed


class FirestoreChainStore:
    def __init__(self, client: Any) -> None:
        self._client = client
        self._collection = client.collection("audit_chain_heads")

    async def append(self, scope: str, event: AuditEvent) -> AuditEvent:
        from google.cloud import firestore

        doc_ref = self._collection.document(scope)
        result: dict[str, AuditEvent] = {}

        @firestore.async_transactional
        async def advance(transaction: Any) -> None:
            snapshot = await doc_ref.get(transaction=transaction)
            prev = (snapshot.to_dict() or {}).get("hash", GENESIS) if snapshot.exists else GENESIS
            sealed = seal(event, scope, prev)
            assert sealed.chain is not None
            transaction.set(doc_ref, {"hash": sealed.chain.hash, "updated_at": sealed.timestamp})
            result["event"] = sealed

        await advance(self._client.transaction())
        return result["event"]
