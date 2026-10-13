"""Per-project gate catalog from pydacc.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

from .gate import Check


def load_checks(root: Path) -> list[Check] | None:
    """Read `[[checks]]` from pydacc.toml; None when the file is absent."""
    path = root / "pydacc.toml"
    if not path.exists():
        return None
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    checks = []
    for entry in data.get("checks", []):
        checks.append(
            Check(name=str(entry["name"]), command=[str(c) for c in entry["command"]])
        )
    return checks
