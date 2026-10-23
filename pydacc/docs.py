"""Docs registry: discover, import, render and validate RFC/plan/user docs and stories.

Docs are Python modules (content = typed code, see :mod:`pydacc.spec`) imported
by this registry and rendered to md/json. One source, many forms — the
"self-inspecting documentation manager".

One decision kind — RFC: a module contract ``__rfc__.py`` plus numbered
decisions ``rfc/NNNN.py``; business planning lives in ``plan/NNNN.py``.
User stories ``stories/NNNN.py`` are loaded here; their checks, composition
across modules and rendering live in :mod:`pydacc.stories`.
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass, replace
from pathlib import Path

from .spec import PRIORITIES, Doc, RFC_SECTIONS, Ref, Status, Story

RFC_FILENAME = "__rfc__.py"  # module contract (root, pairs with __manifest__.py)
RFC_DIRNAME = "rfc"          # numbered decisions rfc/NNNN.py (not imported by Odoo)
PLAN_DIRNAME = "plan"        # business planning plan/NNNN.py
STORY_DIRNAME = "stories"    # user stories stories/NNNN.py
USER_DOC_DIRNAME = "docs"
USER_DOC_FILENAME = "user.py"
USER_DOC_MD = "user.md"

KINDS = ("rfc", "plan", "user", "story")

Key = tuple[str, str, str]  # (module, kind, ident); contracts/user use ident == ''


@dataclass(frozen=True)
class Located:
    path: Path   # absolute path to the .py doc module
    kind: str    # 'rfc' | 'plan' | 'user' | 'story'
    layer: str   # 'base' | 'country' | 'solution'
    module: str  # module dir name, e.g. 'payroll_core'
    ident: str   # decision/story number ('0001') or ''
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
            contract = mod_dir / RFC_FILENAME
            if contract.is_file():
                located.append(
                    Located(contract, "rfc", layer, module, "", str(contract.relative_to(root)))
                )
            for dirname, kind in ((RFC_DIRNAME, "rfc"), (PLAN_DIRNAME, "plan"), (STORY_DIRNAME, "story")):
                dec_dir = mod_dir / dirname
                if dec_dir.is_dir():
                    for dec_file in sorted(dec_dir.glob("*.py")):
                        located.append(
                            Located(
                                dec_file, kind, layer, module, dec_file.stem,
                                str(dec_file.relative_to(root)),
                            )
                        )
            user_py = mod_dir / USER_DOC_DIRNAME / USER_DOC_FILENAME
            if user_py.is_file():
                located.append(
                    Located(user_py, "user", layer, module, "", str(user_py.relative_to(root)))
                )
    return located


def _synthetic_name(loc: Located) -> str:
    return f"angaralink_doc_{loc.layer}_{loc.module}_{loc.kind}_{loc.ident or 'main'}"


def load(root: Path, loc: Located) -> Doc | Story:
    """Import a doc module by path under a synthetic name and return its Doc
    (or its Story for ``stories/NNNN.py``)."""
    name = _synthetic_name(loc)
    spec = importlib.util.spec_from_file_location(name, loc.path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {loc.rel}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = Story if loc.kind == "story" else Doc
    docs = [v for v in vars(module).values() if isinstance(v, expected)]
    if len(docs) != 1:
        raise ValueError(f"{loc.rel}: expected exactly one {expected.__name__}, found {len(docs)}")
    doc = docs[0]
    if loc.kind in ("rfc", "plan", "story"):
        # ident is the file name (single source), never duplicated in content.
        doc = replace(doc, ident=loc.ident)
    return doc


def _index(located: list[Located]) -> dict[Key, Located]:
    return {(l.module, l.kind, l.ident): l for l in located}


Stories = dict[Key, tuple[Located, Story]]


def _load_all(
    root: Path,
) -> tuple[list[Located], dict[Key, Located], dict[Key, tuple[Located, Doc]], Stories, list[str]]:
    """Load every doc and story, collecting import problems (never raising)."""
    located = discover(root)
    index = _index(located)
    docs: dict[Key, tuple[Located, Doc]] = {}
    stories: Stories = {}
    problems: list[str] = []
    for loc in located:
        try:
            doc = load(root, loc)
        except Exception as exc:  # noqa: BLE001 — report, don't crash
            problems.append(f"{loc.rel}: {exc}")
            continue
        key = (loc.module, loc.kind, loc.ident)
        if isinstance(doc, Story):
            stories[key] = (loc, doc)
        else:
            docs[key] = (loc, doc)
    return located, index, docs, stories, problems


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
    """(docs, superseded_by, load_problems) for CLI/API consumers; no stories."""
    _, _, docs, _, problems = _load_all(root)
    return docs, _superseded_by(docs), problems


def loaded_stories(root: Path) -> tuple[Stories, list[str]]:
    """(stories, load_problems): every ``stories/NNNN.py`` keyed (module, 'story', ident)."""
    _, _, _, stories, problems = _load_all(root)
    return stories, problems


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


def _impl_value(doc: Doc) -> str | None:
    return doc.implementation.value if doc.implementation is not None else None


def to_dict(loc: Located, doc: Doc, effective: Status) -> dict:
    return {
        "kind": loc.kind,
        "layer": loc.layer,
        "module": loc.module,
        "ident": loc.ident,
        "title": doc.title,
        "status": _status_value(doc),
        "effective_status": effective.value,
        "implementation": _impl_value(doc),
        "summary": doc.summary,
        "sections": [{"title": s.title, "body": s.body} for s in doc.sections],
        "invariants": list(doc.invariants),
        "open_questions": list(doc.open_questions),
        "references": [{"module": r.module, "kind": r.kind, "ident": r.ident} for r in doc.references],
        "supersedes": [{"module": r.module, "kind": r.kind, "ident": r.ident} for r in doc.supersedes],
        "requirements": [
            {
                "ident": q.ident, "what": q.what, "why": q.why, "affects": q.affects,
                "used_in": list(q.used_in), "priority": q.priority, "target": q.target,
                "implementation": q.implementation.value,
                "refs": [{"module": r.module, "kind": r.kind, "ident": r.ident} for r in q.refs],
            }
            for q in doc.requirements
        ],
    }


def render_json(loc: Located, doc: Doc, effective: Status) -> str:
    return json.dumps(to_dict(loc, doc, effective), ensure_ascii=False, indent=2)


def render_md(loc: Located, doc: Doc, effective: Status) -> str:
    kind_label = {"rfc": "RFC", "plan": "Plan", "user": "Пользовательская документация"}[loc.kind]
    lines: list[str] = [f"# {doc.title}", ""]
    meta = [f"- **Модуль:** `{loc.module}`", f"- **Тип:** {kind_label}"]
    if loc.ident:
        meta.append(f"- **Номер:** {loc.ident}")
    meta.append(f"- **Статус:** {effective.value}")
    if doc.implementation is not None:
        meta.append(f"- **Реализация:** {doc.implementation.value}")
    lines.extend(meta)
    if doc.summary:
        lines += ["", doc.summary]
    for s in doc.sections:
        lines += ["", f"## {s.title}", "", s.body]
    if doc.requirements:
        lines += ["", "## Требования", ""]
        for q in doc.requirements:
            target = f" → `{q.target}`" if q.target else ""
            lines += [
                f"### {q.ident}. {q.what}",
                "",
                f"- **Приоритет:** {q.priority}{target}; реализация: {q.implementation.value}",
                f"- **Зачем:** {q.why}",
                f"- **Влияет на:** {q.affects}",
                f"- **Где используется:** {'; '.join(q.used_in)}",
            ]
            if q.refs:
                lines.append("- **Связано:** " + ", ".join(f"`{_fmt(_key_of(r))}`" for r in q.refs))
            lines.append("")
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
    """Hard problems (empty == valid): import, kind/module, sections, refs.

    Enforces: every reference/supersedes target exists, the supersedes graph is
    acyclic, CANCELLED docs do not supersede anything, and rfc/plan docs carry
    every required section (RFC_SECTIONS). Stories: see
    :func:`pydacc.stories.story_problems`.
    """
    from .stories import story_problems  # stories builds on this registry

    located, index, docs, stories, problems = _load_all(root)
    for loc in located:
        doc = docs.get((loc.module, loc.kind, loc.ident))
        if doc is None:
            continue
        _, doc = doc
        if doc.kind != loc.kind:
            problems.append(f"{loc.rel}: content kind {doc.kind!r} != file kind {loc.kind!r}")
        if doc.module != loc.module:
            problems.append(f"{loc.rel}: content module {doc.module!r} != dir {loc.module!r}")
        if not isinstance(doc.summary, str):
            problems.append(f"{loc.rel}: summary is {type(doc.summary).__name__}, expected str")
        for s in doc.sections:
            if not isinstance(s.title, str) or not isinstance(s.body, str):
                problems.append(f"{loc.rel}: section {s.title!r}: title/body must be str")
        if doc.kind in ("rfc", "plan"):
            titles = {s.title for s in doc.sections}
            for required in RFC_SECTIONS:
                if required not in titles:
                    problems.append(f"{loc.rel}: missing required section {required!r}")
        for r in doc.references + doc.supersedes:
            if _key_of(r) not in index:
                problems.append(f"{loc.rel}: ref to missing doc `{_fmt(_key_of(r))}`")
        problems += _requirement_problems(loc.rel, doc, index)
        if doc.status is Status.CANCELLED and doc.supersedes:
            problems.append(f"{loc.rel}: CANCELLED must not supersede another doc")
    cycle = _find_cycle(_supersedes_graph(docs))
    if cycle:
        chain = " -> ".join(_fmt(k) for k in cycle)
        problems.append(f"supersedes cycle: {chain}")
    if stories:
        problems += story_problems(root, docs, stories)
    return problems


def _requirement_problems(rel: str, doc: Doc, index) -> list[str]:
    """Требование без ответа «зачем / на что влияет / где используется» — не требование."""
    problems: list[str] = []
    seen: set[str] = set()
    for q in doc.requirements:
        label = f"{rel}: requirement {q.ident or '?'}"
        if not q.ident:
            problems.append(f"{label}: empty ident")
        elif q.ident in seen:
            problems.append(f"{label}: duplicate ident")
        seen.add(q.ident)
        for name in ("what", "why", "affects"):
            if not getattr(q, name).strip():
                problems.append(f"{label}: empty {name!r}")
        if not any(u.strip() for u in q.used_in):
            problems.append(f"{label}: empty 'used_in'")
        if q.priority not in PRIORITIES:
            problems.append(f"{label}: priority {q.priority!r} not in {PRIORITIES}")
        for r in q.refs:
            if _key_of(r) not in index:
                problems.append(f"{label}: ref to missing doc `{_fmt(_key_of(r))}`")
    return problems


def warnings(root: Path) -> list[str]:
    """Soft warnings (do not fail the gate): accepted docs referencing drafts."""
    _, _, docs, _, _ = _load_all(root)
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
    """One table: what is actually current, per doc, with both status axes.

    Stories have no status axes: their row says ``story``.
    """
    located, _, docs, stories, problems = _load_all(root)
    sb = _superseded_by(docs)
    rows = [f"{'doc':<36} {'declared':<11} {'effective':<11} {'impl':<12} title"]
    for key in sorted([*docs, *stories]):
        if key in stories:
            rows.append(f"{_fmt(key):<36} {'story':<11} {'':<11} {'':<12} {stories[key][1].title}")
            continue
        loc, doc = docs[key]
        eff = effective_status(doc, key in sb)
        impl = doc.implementation.value if doc.implementation is not None else ""
        rows.append(f"{_fmt(key):<36} {doc.status.value:<11} {eff.value:<11} {impl:<12} {doc.title}")
    if problems:
        rows.append("")
        rows += [f"! {p}" for p in problems]
    return "\n".join(rows)


def graph_report(root: Path, module: str | None) -> str:
    """Show the supersedes chain per module (было → стало)."""
    _, _, docs, _, _ = _load_all(root)
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

    Only user docs are committed as .md; rfc/plan render on demand.
    """
    located, _, docs, _, _ = _load_all(root)
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
