from __future__ import annotations

from pathlib import Path

import pytest

from sf_mcp.config import load_settings
from sf_mcp.errors import ConfigError

LOCAL = {"SFMCP_ENV": "local", "SFMCP_KEY_PEPPER": "k" * 40}


def test_local_defaults() -> None:
    settings = load_settings(LOCAL)
    assert settings.store_backend == "memory"
    assert settings.xff_client_index == -2
    assert settings.cache_seconds == 10


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, "SFMCP_ENV is required"),
        ({"SFMCP_ENV": "qa"}, "SFMCP_ENV must be one of"),
        ({**LOCAL, "SFMCP_KEY_PEPPER": "short"}, "at least 32 bytes"),
        ({**LOCAL, "SFMCP_CACHE_SECONDS": "30"}, "at most 10"),
        ({"SFMCP_ENV": "dev", "SFMCP_STORE": "memory"}, "memory store is allowed in local only"),
    ],
)
def test_unsafe_settings_stop_startup(env: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_settings(env)


def test_deployed_environment_requires_file_pepper_and_iap(tmp_path: Path) -> None:
    pepper = tmp_path / "pepper"
    pepper.write_text("z" * 48)
    base = {"SFMCP_ENV": "dev", "SFMCP_GCP_PROJECT": "proj"}
    with pytest.raises(ConfigError, match="SFMCP_IAP_AUDIENCE_ADMIN is required"):
        load_settings({**base, "SFMCP_KEY_PEPPER_FILE": str(pepper)})
    with_iap = {**base, "SFMCP_IAP_AUDIENCE_ADMIN": "/projects/1/x"}
    with pytest.raises(ConfigError, match="SFMCP_KEY_PEPPER_FILE is required"):
        load_settings({**with_iap, "SFMCP_KEY_PEPPER": "z" * 48})
    settings = load_settings({**with_iap, "SFMCP_KEY_PEPPER_FILE": str(pepper)})
    assert settings.store_backend == "firestore"
    assert settings.key_pepper == b"z" * 48


def test_dev_admin_bypass_is_local_only(tmp_path: Path) -> None:
    pepper = tmp_path / "pepper"
    pepper.write_text("z" * 48)
    with pytest.raises(ConfigError, match="allowed in local only"):
        load_settings(
            {
                "SFMCP_ENV": "dev",
                "SFMCP_GCP_PROJECT": "proj",
                "SFMCP_KEY_PEPPER_FILE": str(pepper),
                "SFMCP_IAP_AUDIENCE_ADMIN": "/projects/1/x",
                "SFMCP_DEV_ADMIN_EMAIL": "me@example.com",
            }
        )
