from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HealthInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class HealthOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    service: str
    version: str
    environment: str
    policy_version: str
    read_only: bool
    time: str
