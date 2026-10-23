from __future__ import annotations

from pathlib import Path

import pytest
from support import POLICY, write_policy

from sf_mcp.errors import PolicyError
from sf_mcp.policy.loader import check_alignment, load_policy
from sf_mcp.tools.registry import build_registry

REPO_POLICY = Path(__file__).resolve().parents[2] / "policy"


def test_shipped_policy_loads_and_matches_the_registry() -> None:
    bundle = load_policy(REPO_POLICY)
    check_alignment(bundle, build_registry())
    assert len(bundle.version) == 12


def test_version_changes_when_content_changes(tmp_path: Path) -> None:
    first = load_policy(write_policy(tmp_path / "a"))
    second = load_policy(
        write_policy(tmp_path / "b", {"limits.yaml": POLICY["limits.yaml"].replace("60", "61", 1)})
    )
    assert first.version != second.version


BROKEN = {
    "unknown field": (
        "tools.yaml",
        "tools:\n  health:\n    enabled: true\n    environments: [local]\n    extra: 1\n",
    ),
    "bad yaml": ("tools.yaml", "tools: [unclosed\n"),
    "grant on unknown bu": (
        "clients.yaml",
        "clients:\n  - client_id: c1\n    name: C\n    owner: o@example.com\n    environments: [local]\n"
        "    allowed_sources: ['*']\n    grants:\n      - bu: nowhere\n        roles: [viewer]\n",
    ),
    "duplicate client": (
        "clients.yaml",
        "clients:\n" + "  - client_id: c1\n    name: C\n    owner: o@example.com\n    environments: [local]\n"
        "    allowed_sources: ['*']\n" * 2,
    ),
    "pii read": (
        "clients.yaml",
        "clients:\n  - client_id: c1\n    name: C\n    owner: o@example.com\n    environments: [local]\n"
        "    allowed_sources: ['*']\n    pii_read: true\n",
    ),
    "bad cidr": (
        "clients.yaml",
        "clients:\n  - client_id: c1\n    name: C\n    owner: o@example.com\n    environments: [local]\n"
        "    allowed_sources: ['10.0.0.0/33']\n",
    ),
    "unknown role": (
        "clients.yaml",
        "clients:\n  - client_id: c1\n    name: C\n    owner: o@example.com\n    environments: [local]\n"
        "    allowed_sources: ['*']\n    grants:\n      - bu: sandbox\n        roles: [approver]\n",
    ),
    "approvers on unknown bu": ("humans.yaml", "humans:\n  approvers:\n    nowhere: [a@example.com]\n"),
    "page bounds": ("limits.yaml", POLICY["limits.yaml"].replace("page_default: 50", "page_default: 250")),
    "keys per client above two": (
        "limits.yaml",
        POLICY["limits.yaml"].replace("keys_per_client: 2", "keys_per_client: 3"),
    ),
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_invalid_policy_stops_startup(tmp_path: Path, case: str) -> None:
    name, content = BROKEN[case]
    directory = write_policy(tmp_path / "policy", {name: content})
    with pytest.raises(PolicyError):
        load_policy(directory)


def test_missing_file_stops_startup(tmp_path: Path) -> None:
    directory = write_policy(tmp_path / "policy")
    (directory / "humans.yaml").unlink()
    with pytest.raises(PolicyError, match="missing policy file"):
        load_policy(directory)


def test_registry_and_policy_drift_stops_startup(tmp_path: Path) -> None:
    extra = (
        "tools:\n  health:\n    enabled: true\n    environments: [local]\n"
        "  ghost_tool:\n    enabled: true\n    environments: [local]\n"
    )
    bundle = load_policy(write_policy(tmp_path / "a", {"tools.yaml": extra}))
    with pytest.raises(PolicyError, match="unknown tools: ghost_tool"):
        check_alignment(bundle, build_registry())
    empty = load_policy(write_policy(tmp_path / "b", {"tools.yaml": "tools: {}\n"}))
    with pytest.raises(PolicyError, match="without a policy entry: health"):
        check_alignment(empty, build_registry())
