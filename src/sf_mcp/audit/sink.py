"""Write sealed audit events as one JSON line on stdout.

Cloud Run ships stdout to Cloud Logging. A log sink filtered on `jsonPayload.event_type` starting with
"sfmcp.audit" routes these lines to the locked audit bucket and to BigQuery.
"""

from __future__ import annotations

import json
import sys
from typing import Protocol, TextIO

from sf_mcp.audit.chain import AuditEvent


class AuditSink(Protocol):
    async def write(self, event: AuditEvent) -> None: ...


class StdoutAuditSink:
    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream

    async def write(self, event: AuditEvent) -> None:
        entry = event.model_dump(mode="json")
        entry["severity"] = "NOTICE"
        entry["message"] = event.event_type
        stream = self._stream or sys.stdout
        stream.write(json.dumps(entry, separators=(",", ":")) + "\n")
        stream.flush()


class MemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def write(self, event: AuditEvent) -> None:
        self.events.append(event)
