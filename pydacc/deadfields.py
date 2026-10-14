"""Dead-field candidates: model fields defined but never referenced.

Static, candidate-level (like coverage "not covered"): a field may still be
referenced by the ORM (``related=``/``compute=`` targets, reports, ``_order``
substrings, external tools) which this static scan does not see. Review each
hit manually — this is an inventory, not a verdict.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

STD_FIELDS = {
    "id",
    "name",
    "display_name",
    "create_uid",
    "create_date",
    "write_uid",
    "write_date",
    "active",
    "company_id",
    "state",
    "sequence",
    "__last_update",
}


@dataclass(frozen=True)
class FieldDef:
    model: str
    field: str
    path: str
    lineno: int


def _field_decl(stmt: ast.stmt) -> str | None:
    """Return the field name when the stmt is ``x = fields.Xxx(...)``."""
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if not isinstance(target, ast.Name):
        return None
    value = stmt.value
    if not isinstance(value, ast.Call):
        return None
    func = value.func
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "fields"
    ):
        return target.id
    return None


def _model_name(node: ast.ClassDef) -> str | None:
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name) and t.id == "_name":
                    if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                        return stmt.value.value
    return None


def _collect_defs(addons: Path) -> list[FieldDef]:
    defs: list[FieldDef] = []
    for path in sorted(addons.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            model = _model_name(node)
            if model is None:
                continue
            for stmt in node.body:
                field = _field_decl(stmt)
                if field:
                    defs.append(FieldDef(model, field, str(path.relative_to(addons.parent)), stmt.lineno))
    return defs


def _referenced_anywhere(addons: Path, field: str, skip_path: str, skip_lineno: int) -> bool:
    word = re.compile(r"\b%s\b" % re.escape(field))
    for path in addons.rglob("*"):
        if path.suffix not in {".py", ".xml"}:
            continue
        if "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(addons.parent))
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            # Skip the definition line itself (`field = fields.Xxx(...)`).
            if rel == skip_path and lineno == skip_lineno:
                continue
            if word.search(line):
                return True
    return False


def dead_fields(root: Path) -> list[FieldDef]:
    addons = root / "addons"
    if not addons.is_dir():
        return []
    hits: list[FieldDef] = []
    for d in _collect_defs(addons):
        if d.field in STD_FIELDS:
            continue
        if not _referenced_anywhere(addons, d.field, d.path, d.lineno):
            hits.append(d)
    return hits


def report(root: Path) -> str:
    hits = dead_fields(root)
    if not hits:
        return "no dead-field candidates"
    lines: list[str] = []
    current: str | None = None
    for d in sorted(hits, key=lambda d: (d.model, d.field)):
        if d.model != current:
            lines.append(f"{d.model}:")
            current = d.model
        lines.append(f"  {d.field}  ({d.path}:{d.lineno})")
    return "\n".join(lines)
