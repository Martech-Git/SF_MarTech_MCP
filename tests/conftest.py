from __future__ import annotations

from pathlib import Path

import pytest
from support import FakeClock, Stores, write_policy


@pytest.fixture
def policy_dir(tmp_path: Path) -> Path:
    return write_policy(tmp_path / "policy")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def stores() -> Stores:
    return Stores()
