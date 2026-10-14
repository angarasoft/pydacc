"""Per-project gate catalog from pydacc.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

from .gate import Check


def _load(root: Path) -> dict | None:
    path = root / "pydacc.toml"
    if not path.exists():
        return None
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_checks(root: Path) -> list[Check] | None:
    """Read `[[checks]]` from pydacc.toml; None when the file is absent."""
    data = _load(root)
    if data is None:
        return None
    checks = []
    for entry in data.get("checks", []):
        checks.append(
            Check(
                name=str(entry["name"]),
                command=[str(c) for c in entry["command"]],
                snapshot=bool(entry.get("snapshot", False)),
            )
        )
    return checks


def load_snapshot_links(root: Path) -> list[str]:
    """`[snapshot] link = [...]`: untracked paths symlinked into the index snapshot."""
    data = _load(root) or {}
    return [str(p) for p in data.get("snapshot", {}).get("link", [])]
