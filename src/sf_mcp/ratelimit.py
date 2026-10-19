"""Token buckets per subject (key, BU, tenant). Per instance; Cloud Armor limits sit in front."""

from __future__ import annotations

from sf_mcp.clock import Clock


class RateLimiter:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, subject: str, per_minute: int) -> bool:
        """Take one token from `subject`'s bucket. The bucket holds `per_minute` tokens and refills evenly."""
        now = self._clock.monotonic()
        capacity = float(per_minute)
        tokens, last = self._buckets.get(subject, (capacity, now))
        tokens = min(capacity, tokens + (now - last) * capacity / 60.0)
        if tokens < 1.0:
            self._buckets[subject] = (tokens, now)
            return False
        self._buckets[subject] = (tokens - 1.0, now)
        return True
