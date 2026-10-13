"""Static introspection: the cheap catalog for agents (no Odoo runtime).

Finds Odoo models (classes with `_name` or `_inherit`) in Python sources. The
authoritative catalog for the gate comes from runtime introspection (a later
slice); this one answers agent queries fast.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Model:
    name: str            # Odoo `_name`, or the class name when only `_inherit`
    klass: str           # Python class name
    module: str          # nearest package dir name
    path: str            # path relative to the scan root
    inherit: tuple[str, ...]
    fields: tuple[str, ...]


def _str_constant(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _target(stmt: ast.stmt) -> str | None:
    if isinstance(stmt, ast.Assign):
        targets = stmt.targets
    elif isinstance(stmt, ast.AnnAssign):
        targets = [stmt.target]
    else:
        return None
    for target in targets:
        if isinstance(target, ast.Name):
            return target.id
    return None


def scan(root: Path) -> list[Model]:
    models: list[Model] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        module = path.parent.name
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            name = None
            inherit: list[str] = []
            fields: list[str] = []
            for stmt in node.body:
                target = _target(stmt)
                if target is None or not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    continue
                value = getattr(stmt, "value", None)
                if target == "_name":
                    name = _str_constant(value)
                elif target == "_inherit":
                    v = _str_constant(value)
                    if v is not None:
                        inherit.append(v)
                elif target == "_fields" and isinstance(value, ast.Dict):
                    fields = [
                        key.value
                        for key in value.keys
                        if isinstance(key, ast.Constant) and isinstance(key.value, str)
                    ]
            if name or inherit:
                models.append(
                    Model(
                        name=name or node.name,
                        klass=node.name,
                        module=module,
                        path=str(path.relative_to(root)),
                        inherit=tuple(inherit),
                        fields=tuple(fields),
                    )
                )
    return models
