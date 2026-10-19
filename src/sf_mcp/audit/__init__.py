"""Audit events, hash chain and sinks."""

from __future__ import annotations

from sf_mcp.audit.chain import AuditEvent, ChainStore
from sf_mcp.audit.sink import AuditSink


class Auditor:
    """Seals an event into its chain, then writes it. Raises if either step fails."""

    def __init__(self, chain: ChainStore, sink: AuditSink) -> None:
        self._chain = chain
        self._sink = sink

    async def record(self, scope: str, event: AuditEvent) -> AuditEvent:
        sealed = await self._chain.append(scope, event)
        await self._sink.write(sealed)
        return sealed
