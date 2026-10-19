"""User stories: checks, superposition across modules, guide rendering.

A story (``addons/<layer>/<module>/stories/NNNN.py``, :class:`pydacc.spec.Story`)
is either a base story or an extension of a story in a dependency module. The
user guide of a solution is the superposition of the stories of every module
the solution installs (its transitive ``depends``): base stories with the
extensions of in-scope modules applied in dependency order.

Discovery and loading are done by :mod:`pydacc.docs`; this module only reads
``__manifest__.py`` files (``ast``, never imports) for the dependency graph.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

from .docs import Key, Located, Stories, _find_cycle, _fmt, _key_of, loaded_stories
from .spec import Doc, Ref, Scenario, Step, Story

MANIFEST = "__manifest__.py"
TEST_ID_HELP = "<module>.tests.<test_file>[.<Class>[.<method>]]"


# --------------------------------------------------------------------------
# Module graph (from __manifest__.py)


@dataclass(frozen=True)
class ModuleInfo:
    name: str
    layer: str
    path: Path                     # absolute module dir
    rel: str                       # module dir relative to the scan root
    depends: tuple[str, ...] = ()


def _manifest_depends(path: Path) -> tuple[str, ...]:
    """``depends`` of a manifest: the dict literal of the file, read by ``ast``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Dict):
            data = ast.literal_eval(node.value)
            return tuple(str(d) for d in data.get("depends", ()))
    raise ValueError("no dict literal")


def modules(root: Path) -> tuple[dict[str, ModuleInfo], list[str]]:
    """Every ``addons/<layer>/<module>`` dir with its depends; unreadable manifests reported."""
    mods: dict[str, ModuleInfo] = {}
    problems: list[str] = []
    addons = root / "addons"
    if not addons.is_dir():
        return mods, problems
    for layer_dir in sorted(p for p in addons.iterdir() if p.is_dir()):
        for mod_dir in sorted(p for p in layer_dir.iterdir() if p.is_dir()):
            if mod_dir.name in mods:
                continue
            depends: tuple[str, ...] = ()
            manifest = mod_dir / MANIFEST
            if manifest.is_file():
                try:
                    depends = _manifest_depends(manifest)
                except (SyntaxError, ValueError) as exc:
                    problems.append(f"{manifest.relative_to(root)}: cannot read depends: {exc}")
            mods[mod_dir.name] = ModuleInfo(
                mod_dir.name, layer_dir.name, mod_dir, str(mod_dir.relative_to(root)), depends
            )
    return mods, problems


def depends_closure(mods: dict[str, ModuleInfo], module: str) -> set[str]:
    """Transitive ``depends`` of ``module`` (without itself); external deps included as names."""
    seen: set[str] = set()
    stack = list(mods[module].depends) if module in mods else []
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        if name in mods:
            stack.extend(mods[name].depends)
    seen.discard(module)
    return seen


def dependency_order(mods: dict[str, ModuleInfo], names: set[str]) -> list[str]:
    """``names`` with dependencies first, ties by name (Kahn); a depends cycle goes last."""
    pending = {n: {d for d in (mods[n].depends if n in mods else ()) if d in names} for n in names}
    order: list[str] = []
    while pending:
        ready = sorted(n for n, deps in pending.items() if not deps)
        if not ready:  # cycle in manifests: keep going, deterministically
            ready = sorted(pending)
        for n in ready:
            del pending[n]
            order.append(n)
        for deps in pending.values():
            deps.difference_update(ready)
    return order


# --------------------------------------------------------------------------
# Composition


@dataclass(frozen=True)
class ComposedStory:
    """A base story with the extensions of the modules in scope applied."""

    module: str                        # module of the base story
    ident: str
    title: str
    role: str
    goal: str
    benefit: str
    scenarios: tuple[Scenario, ...]
    steps: tuple[Step, ...]            # screenshots relative to the scan root
    modules: tuple[str, ...]           # base module, then extensions in applied order
    implements: tuple[Ref, ...]
    requirements: tuple[str, ...]
    notes: tuple[str, ...] = ()


@dataclass(eq=False)
class _Entry:
    step: Step
    anchor: _Entry | None = None       # the entry it was inserted after (steps_after)

    def inserted_after(self, other: _Entry) -> bool:
        """True when this entry is part of the insertions following ``other``."""
        entry = self.anchor
        while entry is not None:
            if entry is other:
                return True
            entry = entry.anchor
        return False


@dataclass
class _Draft:
    base: tuple[Located, Story]
    scenarios: list[Scenario] = field(default_factory=list)
    steps: list[_Entry] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    implements: list[Ref] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _module_rel(loc: Located) -> Path:
    """``addons/<layer>/<module>`` of a story file."""
    return Path(loc.rel).parent.parent


def _rooted(loc: Located, step: Step) -> Step:
    """Screenshot path relative to the scan root (one guide, many modules)."""
    if not step.screenshot:
        return step
    return Step(step.text, (_module_rel(loc) / step.screenshot).as_posix())


def _extend_unique(target: list, items) -> None:
    for item in items:
        if item not in target:
            target.append(item)


def _insert_after(entries: list[_Entry], anchor_text: str, new: tuple[Step, ...], loc: Located) -> None:
    """Insert after the first step with this exact text and its earlier insertions
    (an extension applied later reads after the ones applied before it)."""
    anchor = next((e for e in entries if e.step.text == anchor_text), None)
    if anchor is None:
        return  # reported by story_problems
    pos = entries.index(anchor) + 1
    while pos < len(entries) and entries[pos].inserted_after(anchor):
        pos += 1
    entries[pos:pos] = [_Entry(_rooted(loc, s), anchor) for s in new]


def _apply(draft: _Draft, loc: Located, story: Story) -> None:
    """Superpose one story (base or extension) onto the draft."""
    for ident, replacement in story.replaces.items():
        for i, sc in enumerate(draft.scenarios):
            if sc.ident == ident:
                draft.scenarios[i] = replacement
                break
    draft.scenarios.extend(story.scenarios)
    for anchor_text, new in story.steps_after.items():
        _insert_after(draft.steps, anchor_text, new, loc)
    draft.steps.extend(_Entry(_rooted(loc, s)) for s in story.steps)
    _extend_unique(draft.modules, [loc.module])
    _extend_unique(draft.implements, story.implements)
    _extend_unique(draft.requirements, story.requirements)
    if story.notes:
        draft.notes.append(story.notes)


def _finish(draft: _Draft) -> ComposedStory:
    loc, base = draft.base
    return ComposedStory(
        module=loc.module, ident=loc.ident, title=base.title,
        role=base.role, goal=base.goal, benefit=base.benefit,
        scenarios=tuple(draft.scenarios), steps=tuple(e.step for e in draft.steps),
        modules=tuple(draft.modules), implements=tuple(draft.implements),
        requirements=tuple(draft.requirements), notes=tuple(draft.notes),
    )


def _compose_keys(stories: Stories, keys: list[Key]) -> ComposedStory:
    """Compose ``keys[0]`` (a base story) with the extensions ``keys[1:]`` in order."""
    draft = _Draft(base=stories[keys[0]])
    for key in keys:
        _apply(draft, *stories[key])
    return _finish(draft)


def _chain(stories: Stories, key: Key) -> list[Key] | None:
    """[base, …, key] following ``extends``; None when broken or cyclic."""
    seen: list[Key] = []
    while key not in seen and key in stories:
        seen.append(key)
        extends = stories[key][1].extends
        if extends is None:
            return list(reversed(seen))
        key = _key_of(extends)
    return None


def _scope(mods: dict[str, ModuleInfo], stories: Stories, solution: str | None) -> set[str]:
    if solution is None:
        return set(mods) | {k[0] for k in stories}
    if solution not in mods:
        raise ValueError(f"unknown solution module {solution!r}")
    return depends_closure(mods, solution) | {solution}


def _compose(mods: dict[str, ModuleInfo], stories: Stories, solution: str | None) -> list[ComposedStory]:
    scope = _scope(mods, stories, solution)
    rank = {m: i for i, m in enumerate(dependency_order(mods, scope))}
    chains = {k: _chain(stories, k) for k in stories if k[0] in scope}
    # Extensions per base, applied in dependency order of their modules.
    extensions: dict[Key, list[Key]] = {}
    for key, chain in chains.items():
        if chain and len(chain) > 1 and all(k[0] in scope for k in chain):
            extensions.setdefault(chain[0], []).append(key)
    bases = sorted((k for k, c in chains.items() if c == [k]), key=lambda k: (rank[k[0]], k))
    composed: list[ComposedStory] = []
    for base in bases:
        exts = sorted(
            extensions.get(base, []),
            key=lambda k: (rank[k[0]], len(chains[k] or ()), k),
        )
        composed.append(_compose_keys(stories, [base, *exts]))
    return composed


def compose(root: Path, solution: str | None = None) -> list[ComposedStory]:
    """Stories of a solution: modules in scope = the solution and its transitive
    ``depends`` (every module when ``solution`` is None); base stories ordered by
    module dependency, then number. Broken links are skipped (``docs check``
    reports them). Raises ValueError for an unknown solution module."""
    mods, _ = modules(root)
    stories, _ = loaded_stories(root)
    return _compose(mods, stories, solution)


# --------------------------------------------------------------------------
# Checks (`pydacc docs check`)


class _TestIndex:
    """Resolves dotted test ids against test files (AST, parsed once per file)."""

    def __init__(self, root: Path, mods: dict[str, ModuleInfo]):
        self.root = root
        self.mods = mods
        self._classes: dict[Path, dict[str, set[str]] | str] = {}

    def path(self, test_id: str) -> Path | None:
        parts = test_id.split(".")
        if len(parts) < 3 or parts[1] != "tests" or parts[0] not in self.mods:
            return None
        return self.mods[parts[0]].path / "tests" / f"{parts[2]}.py"

    def _parse(self, path: Path) -> dict[str, set[str]] | str:
        if path not in self._classes:
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                self._classes[path] = f"cannot parse: {exc.msg}"
            else:
                self._classes[path] = {
                    node.name: {
                        f.name for f in node.body
                        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                    }
                    for node in tree.body if isinstance(node, ast.ClassDef)
                }
        return self._classes[path]

    def problem(self, test_id: str) -> str | None:
        parts = test_id.split(".")
        if not 3 <= len(parts) <= 5 or parts[1] != "tests" or not all(parts):
            return f"malformed test id (expected {TEST_ID_HELP})"
        if parts[0] not in self.mods:
            return f"no module {parts[0]!r}"
        path = self.path(test_id)
        rel = path.relative_to(self.root).as_posix()
        if not path.is_file():
            return f"no file {rel}"
        if len(parts) == 3:
            return None
        classes = self._parse(path)
        if isinstance(classes, str):
            return f"{rel}: {classes}"
        if parts[3] not in classes:
            return f"no class {parts[3]!r} in {rel}"
        if len(parts) == 5 and parts[4] not in classes[parts[3]]:
            return f"no method '{parts[3]}.{parts[4]}' in {rel}"
        return None


@dataclass
class _Ctx:
    root: Path
    docs: dict[Key, tuple[Located, Doc]]
    stories: Stories
    mods: dict[str, ModuleInfo]
    tests: _TestIndex


def _content_problems(story: Story) -> list[str]:
    """a) the shape of a base story or an extension."""
    problems: list[str] = []
    if not story.title.strip():
        problems.append("empty 'title'")
    if story.extends is None:
        for name in ("role", "goal", "benefit"):
            if not getattr(story, name).strip():
                problems.append(f"empty {name!r}")
        if not story.scenarios:
            problems.append("base story needs at least one scenario")
        if story.replaces or story.steps_after:
            problems.append("replaces/steps_after need extends")
    elif story.role or story.goal or story.benefit:
        problems.append("extension must not set role/goal/benefit (taken from the base story)")
    return problems


def _scenario_problems(story: Story) -> list[str]:
    """b) scenario idents unique within the story; Дано/Когда/Тогда filled."""
    problems: list[str] = []
    seen: set[str] = set()
    for sc in story.scenarios:
        if sc.ident in seen:
            problems.append(f"scenario {sc.ident!r}: duplicate ident")
        seen.add(sc.ident)
    for key, sc in story.replaces.items():
        if sc.ident != key:
            problems.append(f"replaces {key!r}: scenario ident {sc.ident!r} must equal the key")
    for sc in (*story.scenarios, *story.replaces.values()):
        for name in ("ident", "given", "when", "then"):
            if not getattr(sc, name).strip():
                problems.append(f"scenario {sc.ident or '?'!r}: empty {name!r}")
    for st in _all_steps(story):
        if not st.text.strip():
            problems.append("empty step text")
    return problems


def _all_steps(story: Story) -> list[Step]:
    return [*story.steps, *(s for new in story.steps_after.values() for s in new)]


def _extends_problems(ctx: _Ctx, loc: Located, story: Story) -> list[str]:
    """c) target exists, is a story of a dependency, layers do not invert."""
    target = _key_of(story.extends)
    label = f"extends `{_fmt(target)}`"
    if target[1] != "story":
        return [f"{label}: not a story"]
    if target[0] == loc.module:
        return [f"{label}: must extend a story of another module"]
    if target not in ctx.stories:
        return [f"{label}: missing story"]
    problems: list[str] = []
    if target[0] not in depends_closure(ctx.mods, loc.module):
        problems.append(f"{label}: module {target[0]!r} is not in the depends closure of {loc.module!r}")
    target_loc = ctx.stories[target][0]
    if loc.layer == "base" and target_loc.layer == "country":
        problems.append(f"{label}: a base-layer story cannot extend a country-layer story")
    return problems


def _superposition_problems(ctx: _Ctx, loc: Located, story: Story) -> list[str]:
    """b, d) against the composed base (the extends chain up to this story)."""
    chain = _chain(ctx.stories, (loc.module, "story", loc.ident))
    if not chain:
        return []  # broken/cyclic: reported by extends/cycle checks
    base = _compose_keys(ctx.stories, chain[:-1])
    base_ids = {sc.ident for sc in base.scenarios}
    base_steps = {s.text for s in base.steps}
    label = f"`{_fmt(chain[0])}`"
    problems: list[str] = []
    for key in story.replaces:
        if key not in base_ids:
            problems.append(f"replaces {key!r}: no such scenario in composed base {label}")
    for sc in story.scenarios:
        if sc.ident in base_ids:
            problems.append(f"scenario {sc.ident!r} collides with composed base {label} (use replaces)")
    for anchor in story.steps_after:
        if anchor not in base_steps:
            problems.append(f"steps_after {anchor!r}: no such step in composed base {label}")
    return problems


def _implemented(ctx: _Ctx, loc: Located) -> list[Ref]:
    """Implements of the story and of the stories it extends."""
    chain = _chain(ctx.stories, (loc.module, "story", loc.ident)) or [(loc.module, "story", loc.ident)]
    return [r for k in chain for r in ctx.stories[k][1].implements]


def _implements_problems(ctx: _Ctx, loc: Located, story: Story) -> list[str]:
    """e) implements → existing rfc/plan docs; requirements → their requirement idents."""
    problems: list[str] = []
    for r in story.implements:
        key = _key_of(r)
        if r.kind not in ("rfc", "plan"):
            problems.append(f"implements `{_fmt(key)}`: not an rfc/plan doc")
        elif key not in ctx.docs:
            problems.append(f"implements `{_fmt(key)}`: missing doc")
    known = {
        q.ident
        for r in _implemented(ctx, loc) if _key_of(r) in ctx.docs
        for q in ctx.docs[_key_of(r)][1].requirements
    }
    for ident in story.requirements:
        if ident not in known:
            problems.append(f"requirement {ident!r}: not found in implemented docs")
    return problems


def _test_problems(ctx: _Ctx, story: Story) -> list[str]:
    """f) every test id resolves to a file, class and method."""
    problems: list[str] = []
    for sc in (*story.scenarios, *story.replaces.values()):
        for test_id in sc.tests:
            problem = ctx.tests.problem(test_id)
            if problem:
                problems.append(f"scenario {sc.ident!r}: test {test_id!r}: {problem}")
    return problems


def _screenshot_problems(ctx: _Ctx, loc: Located, story: Story) -> list[str]:
    """g) a screenshot is a file inside the module dir."""
    mod_dir = (ctx.root / _module_rel(loc)).resolve()
    problems: list[str] = []
    for st in _all_steps(story):
        if not st.screenshot:
            continue
        path = (mod_dir / st.screenshot).resolve()
        if not path.is_relative_to(mod_dir) or not path.is_file():
            problems.append(
                f"step {st.text!r}: screenshot {st.screenshot!r} not found in {_module_rel(loc).as_posix()}"
            )
    return problems


def _one_story(ctx: _Ctx, loc: Located, story: Story) -> list[str]:
    problems: list[str] = []
    if story.module != loc.module:
        problems.append(f"content module {story.module!r} != dir {loc.module!r}")
    problems += _content_problems(story)
    problems += _scenario_problems(story)
    if story.extends is not None:
        problems += _extends_problems(ctx, loc, story)
        problems += _superposition_problems(ctx, loc, story)
    problems += _implements_problems(ctx, loc, story)
    problems += _test_problems(ctx, story)
    problems += _screenshot_problems(ctx, loc, story)
    return [f"{loc.rel}: {p}" for p in problems]


def _composed_problems(ctx: _Ctx) -> list[str]:
    """Sibling extensions installed together must not add the same scenario ident."""
    problems: list[str] = []
    for composed in _compose(ctx.mods, ctx.stories, None):
        seen: set[str] = set()
        for sc in composed.scenarios:
            if sc.ident in seen:
                problems.append(
                    f"composed story `{composed.module}::story/{composed.ident}`: duplicate scenario"
                    f" {sc.ident!r} (modules {', '.join(composed.modules)})"
                )
            seen.add(sc.ident)
    return problems


def story_problems(root: Path, docs: dict[Key, tuple[Located, Doc]], stories: Stories) -> list[str]:
    """Hard problems of every story (feeds `pydacc docs check`)."""
    mods, problems = modules(root)
    ctx = _Ctx(root, docs, stories, mods, _TestIndex(root, mods))
    for key in sorted(stories):
        problems += _one_story(ctx, *stories[key])
    graph = {k: ([_key_of(s.extends)] if s.extends else []) for k, (_, s) in stories.items()}
    cycle = _find_cycle(graph)
    if cycle:
        problems.append("story extends cycle: " + " -> ".join(_fmt(k) for k in cycle))
    problems += _composed_problems(ctx)
    return problems


# --------------------------------------------------------------------------
# Rendering


def _sentence(role: str, goal: str, benefit: str) -> str:
    text = f"Как {role} я хочу {goal}, чтобы {benefit}"
    return text if text.endswith((".", "!", "?")) else text + "."


def _test_link(root: Path, mods: dict[str, ModuleInfo], test_id: str) -> str:
    path = _TestIndex(root, mods).path(test_id)
    if path is None or not path.is_file():
        return f"`{test_id}`"
    return f"[`{test_id}`]({path.relative_to(root).as_posix()})"


def _steps_md(steps: tuple[Step, ...]) -> list[str]:
    lines: list[str] = []
    for n, st in enumerate(steps, 1):
        marker = f"{n}. "
        lines.append(f"{marker}{st.text}")
        if st.screenshot:
            lines.append(" " * len(marker) + f"![]({st.screenshot})")
    return lines


def _scenario_md(root: Path, mods: dict[str, ModuleInfo], sc: Scenario, level: str) -> list[str]:
    lines = [
        f"{level} {sc.ident}",
        "",
        f"- **Дано:** {sc.given}",
        f"- **Когда:** {sc.when}",
        f"- **Тогда:** {sc.then}",
    ]
    if sc.tests:
        lines.append("- **Тесты:** " + ", ".join(_test_link(root, mods, t) for t in sc.tests))
    return lines + [""]


def _story_body_md(root: Path, mods: dict[str, ModuleInfo], c: ComposedStory, level: str) -> list[str]:
    """Sentence, steps and scenarios of a (composed) story under heading ``level``."""
    lines: list[str] = []
    if c.role or c.goal or c.benefit:
        lines += [_sentence(c.role, c.goal, c.benefit), ""]
    if c.steps:
        lines += [f"{level} Шаги", "", *_steps_md(c.steps), ""]
    if c.scenarios:
        lines += [f"{level} Сценарии", ""]
        for sc in c.scenarios:
            lines += _scenario_md(root, mods, sc, level + "#")
    return lines


def _own(loc: Located, story: Story) -> ComposedStory:
    """A single story as written (no superposition), paths rooted."""
    draft = _Draft(base=(loc, story))
    _apply(draft, loc, story)
    return _finish(draft)


def render_story_md(root: Path, loc: Located, story: Story) -> str:
    """One story file as md: what it says by itself (an extension shows its delta)."""
    mods, _ = modules(root)
    lines = [f"# {story.title}", "", f"- **Модуль:** `{loc.module}`", "- **Тип:** История"]
    lines.append(f"- **Номер:** {loc.ident}")
    if story.extends is not None:
        lines.append(f"- **Расширяет:** `{_fmt(_key_of(story.extends))}`")
    lines.append("")
    lines += _story_body_md(root, mods, _own(loc, story), "##")
    if story.replaces:
        lines += ["## Заменяет сценарии", ""]
        for sc in story.replaces.values():
            lines += _scenario_md(root, mods, sc, "###")
    if story.steps_after:
        lines += ["## Вставляет шаги", ""]
        for anchor, new in story.steps_after.items():
            lines += [f"После «{anchor}»:", "", *_steps_md(tuple(_rooted(loc, s) for s in new)), ""]
    if story.implements:
        lines += ["## Реализует", ""]
        lines += [f"- `{_fmt(_key_of(r))}`" for r in story.implements]
        lines.append("")
    if story.requirements:
        lines += ["## Требования", "", *(f"- {q}" for q in story.requirements), ""]
    if story.notes:
        lines += ["## Примечания", "", story.notes, ""]
    return "\n".join(lines).rstrip() + "\n"


def render_guide_md(root: Path, composed: list[ComposedStory], solution: str | None) -> str:
    """User guide of a solution: one section per composed story."""
    mods, _ = modules(root)
    title = "Руководство пользователя" + (f": {solution}" if solution else "")
    lines = [f"# {title}", ""]
    for c in composed:
        lines += [f"## {c.title}", ""]
        lines += _story_body_md(root, mods, c, "###")
        for note in c.notes:
            lines += [note, ""]
        lines += ["Модули: " + ", ".join(f"`{m}`" for m in c.modules), ""]
    return "\n".join(lines).rstrip() + "\n"


def _ref_dict(r: Ref) -> dict:
    return {"module": r.module, "kind": r.kind, "ident": r.ident}


def _scenario_dict(sc: Scenario) -> dict:
    return {"ident": sc.ident, "given": sc.given, "when": sc.when, "then": sc.then, "tests": list(sc.tests)}


def _step_dict(st: Step) -> dict:
    return {"text": st.text, "screenshot": st.screenshot}


def story_to_dict(loc: Located, story: Story) -> dict:
    return {
        "kind": "story",
        "layer": loc.layer,
        "module": loc.module,
        "ident": loc.ident,
        "title": story.title,
        "role": story.role,
        "goal": story.goal,
        "benefit": story.benefit,
        "extends": _ref_dict(story.extends) if story.extends else None,
        "implements": [_ref_dict(r) for r in story.implements],
        "requirements": list(story.requirements),
        "scenarios": [_scenario_dict(sc) for sc in story.scenarios],
        "replaces": {k: _scenario_dict(sc) for k, sc in story.replaces.items()},
        "steps": [_step_dict(st) for st in story.steps],
        "steps_after": {k: [_step_dict(st) for st in v] for k, v in story.steps_after.items()},
        "notes": story.notes,
    }


def render_story_json(loc: Located, story: Story) -> str:
    return json.dumps(story_to_dict(loc, story), ensure_ascii=False, indent=2)


def composed_to_dict(c: ComposedStory) -> dict:
    return {
        "module": c.module,
        "ident": c.ident,
        "title": c.title,
        "role": c.role,
        "goal": c.goal,
        "benefit": c.benefit,
        "steps": [_step_dict(st) for st in c.steps],
        "scenarios": [_scenario_dict(sc) for sc in c.scenarios],
        "modules": list(c.modules),
        "implements": [_ref_dict(r) for r in c.implements],
        "requirements": list(c.requirements),
        "notes": list(c.notes),
    }


def render_guide_json(composed: list[ComposedStory], solution: str | None) -> str:
    data = {"solution": solution, "stories": [composed_to_dict(c) for c in composed]}
    return json.dumps(data, ensure_ascii=False, indent=2)
