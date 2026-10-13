"""Access layer: the project map for agents and humans."""

from __future__ import annotations

import json
from pathlib import Path

from .introspect_ast import Model, scan


def map_(root: Path, fmt: str = "text") -> str:
    models = scan(root)
    if fmt == "json":
        return json.dumps([m.__dict__ for m in models], indent=2, ensure_ascii=False)
    return "\n".join(f"{m.module}\t{m.name}\t{m.path}" for m in models)
