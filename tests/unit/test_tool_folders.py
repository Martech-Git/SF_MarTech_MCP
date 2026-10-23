"""Each tool folder carries schema, handler, description and tests, and every tool is registered."""

from __future__ import annotations

from pathlib import Path

import sf_mcp.tools
from sf_mcp.tools.registry import build_registry

TOOLS_DIR = Path(sf_mcp.tools.__file__).parent


def tool_folders() -> list[Path]:
    return sorted(p for p in TOOLS_DIR.iterdir() if p.is_dir() and not p.name.startswith("__"))


def test_every_tool_folder_is_complete() -> None:
    for folder in tool_folders():
        names = {p.name for p in folder.iterdir()}
        missing = {"__init__.py", "schema.py", "handler.py", "description.md"} - names
        assert not missing, f"{folder.name} is missing {sorted(missing)}"
        assert any(n.startswith("test_") and n.endswith(".py") for n in names), f"{folder.name} has no tests"
        assert (folder / "description.md").read_text().strip(), f"{folder.name} has an empty description"


def test_every_tool_folder_is_registered() -> None:
    assert {f.name for f in tool_folders()} == set(build_registry())
