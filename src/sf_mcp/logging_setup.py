"""JSON logging with a field allowlist, so payload data cannot reach Cloud Logging by accident.

Only fields named in ALLOWED_FIELDS leave the process. Exceptions are reduced to their class name and
code locations; exception messages are dropped because they can echo request or Salesforce values.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from typing import Any

from opentelemetry import trace

ALLOWED_FIELDS = frozenset(
    {
        "event",
        "reason",
        "key_id",
        "client_id",
        "tool",
        "tool_call_id",
        "code",
        "rule_id",
        "outcome",
        "duration_ms",
        "status",
        "path",
        "method",
        "bu",
        "environment",
        "policy_version",
        "count",
        "version",
    }
)

_RESERVED = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {"message", "asctime"}


class RedactingJsonFormatter(logging.Formatter):
    def __init__(self, gcp_project: str | None = None) -> None:
        super().__init__()
        self._project = gcp_project

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.msg if isinstance(record.msg, str) else type(record.msg).__name__,
            "logger": record.name,
        }
        for key, value in vars(record).items():
            if key in _RESERVED or key not in ALLOWED_FIELDS:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                entry[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            frames = traceback.extract_tb(record.exc_info[2])
            entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "frames": [f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno}:{f.name}" for f in frames[-8:]],
            }
        span = trace.get_current_span().get_span_context()
        if span.is_valid and self._project:
            entry["logging.googleapis.com/trace"] = f"projects/{self._project}/traces/{span.trace_id:032x}"
            entry["logging.googleapis.com/spanId"] = f"{span.span_id:016x}"
        return json.dumps(entry, separators=(",", ":"))


def configure_logging(level: str, gcp_project: str | None) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RedactingJsonFormatter(gcp_project))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Message arguments are never interpolated by the formatter, and third-party loggers stay quiet.
    for noisy in ("uvicorn.access", "httpx", "httpx2", "google", "urllib3", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
