"""The closed set of error codes the server returns, and the denial exception the pipeline raises."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    UNAUTHENTICATED = "UNAUTHENTICATED"
    KILL_SWITCH = "KILL_SWITCH"
    VALIDATION = "VALIDATION"
    NOT_FOUND = "NOT_FOUND"
    PERMISSION = "PERMISSION"
    RATE_LIMITED = "RATE_LIMITED"
    NOT_ENABLED = "NOT_ENABLED"
    POLICY_ERROR = "POLICY_ERROR"
    SFMC_UNAVAILABLE = "SFMC_UNAVAILABLE"
    D360_UNAVAILABLE = "D360_UNAVAILABLE"
    VERIFY_FAILED = "VERIFY_FAILED"
    AUDIENCE_DRIFT = "AUDIENCE_DRIFT"
    INTERNAL = "INTERNAL"


class Denied(Exception):
    """Raised by a pipeline step to stop a tool call.

    `message` is returned to the client, so it must never contain Salesforce data,
    request arguments or secrets. `rule_id` names the policy rule or step that denied.
    """

    def __init__(self, code: ErrorCode, rule_id: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.rule_id = rule_id
        self.message = message


class PolicyError(Exception):
    """The policy bundle failed to load or validate. The server refuses to start."""


class ConfigError(Exception):
    """Runtime configuration is missing or unsafe. The server refuses to start."""
