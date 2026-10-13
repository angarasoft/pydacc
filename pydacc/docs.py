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

Key = tuple[str, str, str]  # (module, kind, ident); rfc/user use ident == ''


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


def _index(located: list[Located]) -> dict[Key, Located]:
    return {(l.module, l.kind, l.ident): l for l in located}


def _load_all(root: Path) -> tuple[list[Located], dict[Key, Located], dict[Key, tuple[Located, Doc]], list[str]]:
    """Load every doc, collecting import problems (never raising)."""
    located = discover(root)
    index = _index(located)
    docs: dict[Key, tuple[Located, Doc]] = {}
    problems: list[str] = []
    for loc in located:
        try:
            doc = load(root, loc)
        except Exception as exc:  # noqa: BLE001 — report, don't crash
            problems.append(f"{loc.rel}: {exc}")
            continue
        docs[(loc.module, loc.kind, loc.ident)] = (loc, doc)
    return located, index, docs, problems


def _key_of(ref: Ref) -> Key:
    return (ref.module, ref.kind, ref.ident)


def _fmt(key: Key) -> str:
    module, kind, ident = key
    return f"{module}::{kind}" + (f"/{ident}" if ident else "")


def _superseded_by(docs: dict[Key, tuple[Located, Doc]]) -> dict[Key, list[Key]]:
    """key -> list of keys that supersede it (computed, never stored)."""
    sb: dict[Key, list[Key]] = {}
    for key, (_, doc) in docs.items():
        for r in doc.supersedes:
            sb.setdefault(_key_of(r), []).append(key)
    return sb


def loaded_docs(root: Path) -> tuple[dict[Key, tuple[Located, Doc]], dict[Key, list[Key]], list[str]]:
    """(docs, superseded_by, load_problems) for CLI/API consumers."""
    _, _, docs, problems = _load_all(root)
    return docs, _superseded_by(docs), problems


def effective_status(doc: Doc, superseded: bool) -> Status:
    return Status.SUPERSEDED if superseded else doc.status


def _supersedes_graph(docs: dict[Key, tuple[Located, Doc]]) -> dict[Key, list[Key]]:
    return {key: [_key_of(r) for r in doc.supersedes] for key, (_, doc) in docs.items()}


def _find_cycle(graph: dict[Key, list[Key]]) -> list[Key] | None:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {k: WHITE for k in graph}

    def dfs(k: Key, stack: list[Key]) -> list[Key] | None:
        color[k] = GRAY
        stack.append(k)
        for t in graph.get(k, []):
            if t not in color:
                continue
            if color[t] == GRAY:
                idx = stack.index(t)
                return stack[idx:] + [t]
            if color[t] == WHITE:
                res = dfs(t, stack)
                if res:
                    return res
        stack.pop()
        color[k] = BLACK
        return None

    for k in graph:
        if color[k] == WHITE:
            res = dfs(k, [])
            if res:
                return res
    return None


def _status_value(doc: Doc) -> str:
    return doc.status.value


def to_dict(loc: Located, doc: Doc, effective: Status) -> dict:
    return {
        "kind": loc.kind,
        "layer": loc.layer,
        "module": loc.module,
        "ident": loc.ident,
        "title": doc.title,
        "status": _status_value(doc),
        "effective_status": effective.value,
        "summary": doc.summary,
        "sections": [{"title": s.title, "body": s.body} for s in doc.sections],
        "invariants": list(doc.invariants),
        "open_questions": list(doc.open_questions),
        "references": [{"module": r.module, "kind": r.kind, "ident": r.ident} for r in doc.references],
        "supersedes": [{"module": r.module, "kind": r.kind, "ident": r.ident} for r in doc.supersedes],
    }


def render_json(loc: Located, doc: Doc, effective: Status) -> str:
    return json.dumps(to_dict(loc, doc, effective), ensure_ascii=False, indent=2)


def render_md(loc: Located, doc: Doc, effective: Status) -> str:
    kind_label = {"rfc": "RFC", "adr": "ADR", "user": "Пользовательская документация"}[loc.kind]
    lines: list[str] = [f"# {doc.title}", ""]
    meta = [f"- **Модуль:** `{loc.module}`", f"- **Тип:** {kind_label}"]
    if loc.ident:
        meta.append(f"- **Номер:** {loc.ident}")
    meta.append(f"- **Статус:** {effective.value}")
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
    if doc.supersedes:
        lines += ["", "## Пересматривает", ""]
        for r in doc.supersedes:
            lines.append(f"- `{_fmt(_key_of(r))}`")
    if doc.references:
        lines += ["", "## Ссылки", ""]
        for r in doc.references:
            lines.append(f"- `{_fmt(_key_of(r))}`")
    return "\n".join(lines).rstrip() + "\n"


def validate(root: Path) -> list[str]:
    """Hard problems (empty == valid): import, kind/module, refs, supersedes.

    Enforces: every reference/supersedes target exists, the supersedes graph is
    acyclic, and DEPRECATED docs do not supersede anything.
    """
    located, index, docs, problems = _load_all(root)
    for loc in located:
        doc = docs.get((loc.module, loc.kind, loc.ident))
        if doc is None:
            continue
        _, doc = doc
        if doc.kind != loc.kind:
            problems.append(f"{loc.rel}: content kind {doc.kind!r} != file kind {loc.kind!r}")
        if doc.module != loc.module:
            problems.append(f"{loc.rel}: content module {doc.module!r} != dir {loc.module!r}")
        for r in doc.references + doc.supersedes:
            if _key_of(r) not in index:
                problems.append(f"{loc.rel}: ref to missing doc `{_fmt(_key_of(r))}`")
        if doc.status is Status.DEPRECATED and doc.supersedes:
            problems.append(f"{loc.rel}: DEPRECATED must not supersede another doc")
    cycle = _find_cycle(_supersedes_graph(docs))
    if cycle:
        chain = " -> ".join(_fmt(k) for k in cycle)
        problems.append(f"supersedes cycle: {chain}")
    return problems


def warnings(root: Path) -> list[str]:
    """Soft warnings (do not fail the gate): accepted docs referencing drafts."""
    _, _, docs, _ = _load_all(root)
    warns: list[str] = []
    for key, (loc, doc) in docs.items():
        if doc.status is not Status.ACCEPTED:
            continue
        for r in doc.references:
            target = _key_of(r)
            if target in docs and docs[target][1].status is Status.DRAFT:
                warns.append(f"{loc.rel}: accepted doc references draft `{_fmt(target)}`")
    return warns


def status_report(root: Path) -> str:
    """One table: what is actually current, per doc."""
    located, _, docs, problems = _load_all(root)
    sb = _superseded_by(docs)
    rows = [f"{'doc':<36} {'declared':<12} {'effective':<12} title"]
    for key in sorted(docs):
        loc, doc = docs[key]
        eff = effective_status(doc, key in sb)
        rows.append(f"{_fmt(key):<36} {doc.status.value:<12} {eff.value:<12} {doc.title}")
    if problems:
        rows.append("")
        rows += [f"! {p}" for p in problems]
    return "\n".join(rows)


def graph_report(root: Path, module: str | None) -> str:
    """Show the supersedes chain per module (было → стало)."""
    _, _, docs, _ = _load_all(root)
    sb = _superseded_by(docs)
    lines: list[str] = []
    for key in sorted(docs):
        if module is not None and key[0] != module:
            continue
        loc, doc = docs[key]
        lines.append(_fmt(key))
        for r in doc.supersedes:
            lines.append(f"  supersedes: {_fmt(_key_of(r))}")
        for src in sb.get(key, []):
            lines.append(f"  superseded_by: {_fmt(src)}")
    return "\n".join(lines) if lines else f"{module or '(all)'}: no docs"


def freshness(root: Path) -> list[str]:
    """Return stale committed user.md files (missing or not matching user.py).

    Only user docs are committed as .md; rfc/adr render on demand.
    """
    located, _, docs, _ = _load_all(root)
    sb = _superseded_by(docs)
    stale: list[str] = []
    for loc in located:
        if loc.kind != "user":
            continue
        doc = docs.get((loc.module, loc.kind, loc.ident))
        if doc is None:
            continue
        _, doc = doc
        md_path = loc.path.parent / USER_DOC_MD
        rendered = render_md(loc, doc, effective_status(doc, (loc.module, loc.kind, loc.ident) in sb))
        if not md_path.exists() or md_path.read_text(encoding="utf-8") != rendered:
            stale.append(str(md_path.relative_to(root)))
    return stale
