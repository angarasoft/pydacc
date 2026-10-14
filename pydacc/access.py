"""Access layer: the project map for agents and humans."""

from __future__ import annotations

import json
from pathlib import Path

from .introspect_ast import Model, scan


def map_(root: Path, fmt: str = "text", addons_only: bool = True) -> str:
    """Project map. By default only ``addons/`` (the project's own modules);
    ``--all`` includes vendored code (build/odoo) and everything else."""
    models = scan(root)
    if addons_only:
        models = [m for m in models if m.path.startswith("addons")]
    if fmt == "json":
        return json.dumps([m.__dict__ for m in models], indent=2, ensure_ascii=False)
    return "\n".join(f"{m.module}\t{m.name}\t{m.path}" for m in models)


def where_(root: Path, file: str) -> str:
    """What introspection knows about a file."""
    models = [m for m in scan(root) if m.path == file or m.path.endswith("/" + file)]
    if not models:
        return f"{file}: no introspected models"
    lines = []
    for model in models:
        lines.append(f"{model.path}: model {model.name} (class {model.klass}, module {model.module})")
        if model.inherit:
            lines.append(f"  _inherit: {', '.join(model.inherit)}")
        if model.fields:
            lines.append(f"  fields: {', '.join(model.fields)}")
    return "\n".join(lines)


def refs_(root: Path, term: str) -> str:
    """Where a term appears, as file:line."""
    hits = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".toml", ".md", ".xml", ".rs"}:
            continue
        if any(part in {".git", "__pycache__", "target", ".venv"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if term in line:
                hits.append(f"{path.relative_to(root)}:{lineno}: {line.strip()}")
    return "\n".join(hits) if hits else f"{term}: not found"


def emit_docs(root: Path) -> dict[str, str]:
    """Generate the agent instruction files (AGENTS.md SSOT + QWEN.md pointer).

    AGENTS.md = the authored rules from docs/agents/rules.md. The model catalog
    is on-demand via `pydacc map`/`where`/`refs`, not committed here.
    """
    rules_path = root / "docs" / "agents" / "rules.md"
    if rules_path.exists():
        rules = rules_path.read_text(encoding="utf-8").rstrip()
    else:
        rules = "# Agent rules\n\n(no docs/agents/rules.md)"
    agents = f"{rules}\n"
    qwen = "# Qwen Code — thin pointer to the single source of truth.\n@AGENTS.md\n"
    return {"AGENTS.md": agents, "QWEN.md": qwen}
