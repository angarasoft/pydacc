"""Docs registry: discover, import, render and validate RFC/ADR/user docs.

Docs are Python modules (content = typed code, see :mod:`pydacc.spec`) imported
by this registry and rendered to md/json. One source, many forms — the
"self-inspecting documentation manager".
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass, replace
from pathlib import Path

from .spec import Doc, Ref, Status

RFC_FILENAME = "__rfc__.py"
ADR_DIRNAME = "__adr__"
USER_DOC_DIRNAME = "docs"
USER_DOC_FILENAME = "user.py"
USER_DOC_MD = "user.md"

KINDS = ("rfc", "adr", "user")


@dataclass(frozen=True)
class Located:
    path: Path   # absolute path to the .py doc module
    kind: str    # 'rfc' | 'adr' | 'user'
    layer: str   # 'base' | 'country' | 'solution'
    module: str  # module dir name, e.g. 'payroll_core'
    ident: str   # adr number ('0001') or ''
    rel: str     # path relative to the scan root


def discover(root: Path) -> list[Located]:
    """Locate every doc module under ``addons/<layer>/<module>/``."""
    located: list[Located] = []
    addons = root / "addons"
    if not addons.is_dir():
        return located
    for layer_dir in sorted(addons.iterdir()):
        if not layer_dir.is_dir():
            continue
        layer = layer_dir.name
        for mod_dir in sorted(layer_dir.iterdir()):
            if not mod_dir.is_dir():
                continue
            module = mod_dir.name
            rfc = mod_dir / RFC_FILENAME
            if rfc.is_file():
                located.append(Located(rfc, "rfc", layer, module, "", str(rfc.relative_to(root))))
            adr_dir = mod_dir / ADR_DIRNAME
            if adr_dir.is_dir():
                for adr_file in sorted(adr_dir.glob("*.py")):
                    located.append(
                        Located(adr_file, "adr", layer, module, adr_file.stem, str(adr_file.relative_to(root)))
                    )
            user_py = mod_dir / USER_DOC_DIRNAME / USER_DOC_FILENAME
            if user_py.is_file():
                located.append(Located(user_py, "user", layer, module, "", str(user_py.relative_to(root))))
    return located


def _synthetic_name(loc: Located) -> str:
    return f"angaralink_doc_{loc.layer}_{loc.module}_{loc.kind}_{loc.ident or 'main'}"


def load(root: Path, loc: Located) -> Doc:
    """Import a doc module by path under a synthetic name and return its Doc."""
    name = _synthetic_name(loc)
    spec = importlib.util.spec_from_file_location(name, loc.path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {loc.rel}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    docs = [v for v in vars(module).values() if isinstance(v, Doc)]
    if len(docs) != 1:
        raise ValueError(f"{loc.rel}: expected exactly one Doc, found {len(docs)}")
    doc = docs[0]
    if loc.kind == "adr":
        # ident is the file name (single source), never duplicated in content.
        doc = replace(doc, ident=loc.ident)
    return doc


def _status_value(doc: Doc) -> str:
    return doc.status.value


def to_dict(loc: Located, doc: Doc) -> dict:
    data = {
        "kind": loc.kind,
        "layer": loc.layer,
        "module": loc.module,
        "ident": loc.ident,
        "title": doc.title,
        "status": _status_value(doc),
        "summary": doc.summary,
        "sections": [{"title": s.title, "body": s.body} for s in doc.sections],
        "invariants": list(doc.invariants),
        "open_questions": list(doc.open_questions),
        "references": [{"module": r.module, "kind": r.kind, "ident": r.ident} for r in doc.references],
    }
    return data


def render_json(loc: Located, doc: Doc) -> str:
    return json.dumps(to_dict(loc, doc), ensure_ascii=False, indent=2)


def render_md(loc: Located, doc: Doc) -> str:
    kind_label = {"rfc": "RFC", "adr": "ADR", "user": "Пользовательская документация"}[loc.kind]
    lines: list[str] = [f"# {doc.title}", ""]
    meta = [f"- **Модуль:** `{loc.module}`", f"- **Тип:** {kind_label}"]
    if loc.ident:
        meta.append(f"- **Номер:** {loc.ident}")
    meta.append(f"- **Статус:** {_status_value(doc)}")
    lines.extend(meta)
    if doc.summary:
        lines += ["", doc.summary]
    for s in doc.sections:
        lines += ["", f"## {s.title}", "", s.body]
    if doc.invariants:
        lines += ["", "## Инварианты", ""]
        lines += [f"- {i}" for i in doc.invariants]
    if doc.open_questions:
        lines += ["", "## Открытые вопросы", ""]
        lines += [f"- {q}" for q in doc.open_questions]
    if doc.references:
        lines += ["", "## Ссылки", ""]
        for r in doc.references:
            target = f"{r.module}::{r.kind}" + (f"/{r.ident}" if r.ident else "")
            lines.append(f"- `{target}`")
    return "\n".join(lines).rstrip() + "\n"


def _index(located: list[Located]) -> dict[tuple[str, str, str], Located]:
    # (module, kind, ident) -> Located; rfc/user use ident == ''.
    return {(l.module, l.kind, l.ident): l for l in located}


def validate(root: Path) -> list[str]:
    """Return a list of problems (empty == valid).

    Checks: import works, kind/module match the file location, status is a
    valid enum (enforced at import), and every ``ref`` resolves to a discovered
    doc in the same project.
    """
    problems: list[str] = []
    located = discover(root)
    index = _index(located)
    seen: dict[tuple[str, str, str], Doc] = {}
    for loc in located:
        try:
            doc = load(root, loc)
        except Exception as exc:  # noqa: BLE001 — report, don't crash
            problems.append(f"{loc.rel}: {exc}")
            continue
        if doc.kind != loc.kind:
            problems.append(f"{loc.rel}: content kind {doc.kind!r} != file kind {loc.kind!r}")
        if doc.module != loc.module:
            problems.append(f"{loc.rel}: content module {doc.module!r} != dir {loc.module!r}")
        seen[(loc.module, loc.kind, loc.ident)] = doc
    for loc in located:
        doc = seen.get((loc.module, loc.kind, loc.ident))
        if doc is None:
            continue
        for r in doc.references:
            key = (r.module, r.kind, r.ident)
            if key not in index:
                target = f"{r.module}::{r.kind}" + (f"/{r.ident}" if r.ident else "")
                problems.append(f"{loc.rel}: ref to missing doc `{target}`")
    return problems


def freshness(root: Path) -> list[str]:
    """Return stale committed user.md files (missing or not matching user.py).

    Only user docs are committed as .md; rfc/adr render on demand.
    """
    stale: list[str] = []
    for loc in discover(root):
        if loc.kind != "user":
            continue
        try:
            doc = load(root, loc)
        except Exception as exc:  # noqa: BLE001
            stale.append(f"{loc.rel}: {exc}")
            continue
        md_path = loc.path.parent / USER_DOC_MD
        rendered = render_md(loc, doc)
        if not md_path.exists() or md_path.read_text(encoding="utf-8") != rendered:
            stale.append(str(md_path.relative_to(root)))
    return stale
