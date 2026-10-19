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
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .docs import Key, Located, Stories, _find_cycle, _fmt, _key_of, loaded_stories
from .spec import DEFAULT_STORY_ORDER, Doc, Ref, Scenario, Step, Story

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
    notes: tuple[str, ...] = ()        # user-facing «Важно», base first, then extensions
    section: str = ""                  # guide chapter of the base story
    order: int = DEFAULT_STORY_ORDER
    menus: tuple[str, ...] = ()        # base menus, then the ones extensions add
    dev_notes: tuple[str, ...] = ()    # developer guide only
    intro: str = ""                    # hand-written user lead (base story)

    @property
    def key(self) -> str:
        return f"{self.module}::story/{self.ident}"


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
    menus: list[str] = field(default_factory=list)
    dev_notes: list[str] = field(default_factory=list)


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
    _extend_unique(draft.menus, story.menus)
    if story.notes:
        draft.notes.append(story.notes)
    if story.dev_notes:
        draft.dev_notes.append(story.dev_notes)


def _finish(draft: _Draft) -> ComposedStory:
    loc, base = draft.base
    return ComposedStory(
        module=loc.module, ident=loc.ident, title=base.title,
        role=base.role, goal=base.goal, benefit=base.benefit,
        scenarios=tuple(draft.scenarios), steps=tuple(e.step for e in draft.steps),
        modules=tuple(draft.modules), implements=tuple(draft.implements),
        requirements=tuple(draft.requirements), notes=tuple(draft.notes),
        section=base.section, order=base.order,
        menus=tuple(draft.menus), dev_notes=tuple(draft.dev_notes), intro=base.intro,
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


MENU_HELP = "<module>.<menu xml id>"


class _MenuIndex:
    """Menu xml ids a module defines in its XML data files (parsed once per module).

    A menu is ``<menuitem id="X">`` (nested ones included) or
    ``<record model="ir.ui.menu" id="X">``; inside its own module the id may be
    written with or without the module prefix. Ids prefixed with another module
    (overrides of foreign menus) do not define a menu of this module.
    """

    def __init__(self, root: Path, mods: dict[str, ModuleInfo]):
        self.root = root
        self.mods = mods
        self._ids: dict[str, tuple[set[str], list[str]]] = {}

    def _scan(self, module: str) -> tuple[set[str], list[str]]:
        if module not in self._ids:
            ids: set[str] = set()
            unparsable: list[str] = []
            for path in sorted(self.mods[module].path.rglob("*.xml")):
                try:
                    tree = ET.parse(path)
                except (ET.ParseError, OSError):
                    unparsable.append(path.relative_to(self.root).as_posix())
                    continue
                for el in tree.iter():
                    if el.tag == "menuitem" or (el.tag == "record" and el.get("model") == "ir.ui.menu"):
                        prefix, _, name = (el.get("id") or "").rpartition(".")
                        if name and prefix in ("", module):
                            ids.add(name)
            self._ids[module] = (ids, unparsable)
        return self._ids[module]

    def problem(self, menu: str, story_module: str) -> str | None:
        module, dot, name = menu.partition(".")
        if not dot or not module or not name or "." in name:
            return f"expected {MENU_HELP}"
        if module != story_module and module not in depends_closure(self.mods, story_module):
            return f"module {module!r} not in depends closure of {story_module!r}"
        if module not in self.mods:
            return f"module {module!r} not found under addons/"
        ids, unparsable = self._scan(module)
        if name in ids:
            return None
        hint = f" (unparsable: {', '.join(unparsable)})" if unparsable else ""
        return f"not found in module {module!r}{hint}"


@dataclass
class _Ctx:
    root: Path
    docs: dict[Key, tuple[Located, Doc]]
    stories: Stories
    mods: dict[str, ModuleInfo]
    tests: _TestIndex
    menus: _MenuIndex


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
        if story.menus and not story.section.strip():
            problems.append("menus need 'section' (the guide chapter)")
        if story.section.strip():
            problems += _guide_text_problems(story)
    else:
        if story.role or story.goal or story.benefit:
            problems.append("extension must not set role/goal/benefit (taken from the base story)")
        if story.section or story.order != DEFAULT_STORY_ORDER:
            problems.append("extension must not set section/order (taken from the base story)")
        if story.intro:
            problems.append("extension must not set intro (taken from the base story)")
    return problems


def _guide_text_problems(story: Story, scenarios_only: bool = False) -> list[str]:
    """A story in the user guide is written for people: the lead paragraph and
    each scenario's title and text by hand (Дано/Когда/Тогда stay for tests)."""
    problems: list[str] = []
    if not scenarios_only and not story.intro.strip():
        problems.append("a story with 'section' needs 'intro' (user guide lead, written by hand)")
    for sc in (*story.scenarios, *story.replaces.values()):
        for name in ("title", "text"):
            if not getattr(sc, name).strip():
                problems.append(f"scenario {sc.ident!r}: a story in the guide needs {name!r}")
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
    if story.menus and not base.section.strip():
        problems.append(f"menus need 'section' in the base story {label}")
    if base.section.strip():
        problems += _guide_text_problems(story, scenarios_only=True)
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


def _menu_problems(ctx: _Ctx, loc: Located, story: Story) -> list[str]:
    """h) every menu xml id resolves to a menu of the module or of its depends closure."""
    problems: list[str] = []
    seen: set[str] = set()
    for menu in story.menus:
        if menu in seen:
            problems.append(f"menu {menu!r}: duplicate")
            continue
        seen.add(menu)
        problem = ctx.menus.problem(menu, loc.module)
        if problem:
            problems.append(f"menu {menu!r}: {problem}")
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
    problems += _menu_problems(ctx, loc, story)
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
    ctx = _Ctx(root, docs, stories, mods, _TestIndex(root, mods), _MenuIndex(root, mods))
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
#
# Two audiences of a solution guide: ``dev`` (stories as specs: scenarios with
# their tests, modules, menus, technical notes) and ``user`` (an end-user
# guide: chapters by section, how-to steps, scenarios as plain rules, «Важно»
# notes; no tests, idents of refs, module names or technical notes).

AUDIENCES = ("dev", "user")
GUIDE_FORMAT = 1               # version of the guide JSON layout (README)
OTHER_SECTION = "Прочее"       # chapter of the stories without a section


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
    heading = f"{sc.ident} — {sc.title}" if sc.title else sc.ident
    lines = [
        f"{level} {heading}",
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


def _placement(section: str, order: int) -> str:
    return section + ("" if order == DEFAULT_STORY_ORDER else f" (порядок {order})")


def render_story_md(root: Path, loc: Located, story: Story) -> str:
    """One story file as md: what it says by itself (an extension shows its delta)."""
    mods, _ = modules(root)
    lines = [f"# {story.title}", "", f"- **Модуль:** `{loc.module}`", "- **Тип:** История"]
    lines.append(f"- **Номер:** {loc.ident}")
    if story.extends is not None:
        lines.append(f"- **Расширяет:** `{_fmt(_key_of(story.extends))}`")
    if story.section:
        lines.append(f"- **Раздел:** {_placement(story.section, story.order)}")
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
    if story.menus:
        lines += ["## Меню", "", *(f"- `{m}`" for m in story.menus), ""]
    if story.notes:
        lines += ["## Примечания", "", story.notes, ""]
    if story.dev_notes:
        lines += ["## Для разработчика", "", story.dev_notes, ""]
    return "\n".join(lines).rstrip() + "\n"


def _dev_guide_md(root: Path, composed: list[ComposedStory], solution: str | None) -> list[str]:
    mods, _ = modules(root)
    title = "Руководство пользователя" + (f": {solution}" if solution else "")
    lines = [f"# {title}", ""]
    for c in composed:
        lines += [f"## {c.title}", ""]
        lines += _story_body_md(root, mods, c, "###")
        for note in c.notes:
            lines += [note, ""]
        for note in c.dev_notes:
            lines += [f"**Для разработчика.** {note}", ""]
        lines += ["Модули: " + ", ".join(f"`{m}`" for m in c.modules), ""]
        if c.section:
            lines += [f"Раздел: {_placement(c.section, c.order)}", ""]
        if c.menus:
            lines += ["Меню: " + ", ".join(f"`{m}`" for m in c.menus), ""]
    return lines


def guide_sections(composed: list[ComposedStory]) -> list[tuple[str, list[ComposedStory]]]:
    """Chapters of the user guide: sections by the minimal ``order`` of their
    stories, then name; «Прочее» (stories without a section) last; stories
    within a chapter by order, then title."""
    groups: dict[str, list[ComposedStory]] = {}
    for c in composed:
        groups.setdefault(c.section.strip() or OTHER_SECTION, []).append(c)
    names = sorted(
        groups, key=lambda s: (s == OTHER_SECTION, min(c.order for c in groups[s]), s)
    )
    return [
        (name, sorted(groups[name], key=lambda c: (c.order, c.title, c.module, c.ident)))
        for name in names
    ]


def _cap(text: str) -> str:
    text = text.strip()
    return text[:1].upper() + text[1:]


def _uncap(text: str) -> str:
    """Lower the first letter of a clause unless it starts an abbreviation (СНИЛС, Т-1)."""
    text = text.strip().rstrip(".").strip()
    return text[:1].lower() + text[1:] if text[1:2].islower() else text


def _end(text: str) -> str:
    return text if text.endswith((".", "!", "?", "…")) else text + "."


def user_lead(c: ComposedStory) -> str:
    """«Кадровик: принять человека на работу, чтобы работник был виден в списке.»"""
    return _end(f"{_cap(c.role)}: {c.goal.strip().rstrip('.')}, чтобы {c.benefit.strip()}")


def user_rule(sc: Scenario) -> str:
    """A scenario as a plain rule: «**Заголовок.** Если <given> и <when>, то <then>.»"""
    label = (sc.title or sc.ident).strip().rstrip(".")
    if sc.text.strip():
        return f"**{label}.** {_end(sc.text.strip())}"
    return _end(f"**{label}.** Если {_uncap(sc.given)} и {_uncap(sc.when)}, то {_uncap(sc.then)}")


def _quote(prefix: str, text: str) -> list[str]:
    first, *rest = text.strip().splitlines() or [""]
    return [f"> {prefix} {first}".rstrip(), *(f"> {line}".rstrip() for line in rest)]


def _user_guide_md(composed: list[ComposedStory]) -> list[str]:
    lines = ["# Руководство пользователя", ""]
    for section, stories in guide_sections(composed):
        lines += [f"## {section}", ""]
        for c in stories:
            lines += [f"### {c.title}", ""]
            if c.intro.strip():
                lines += [c.intro.strip(), ""]
            elif c.role or c.goal or c.benefit:
                lines += [user_lead(c), ""]
            if c.steps:
                lines += ["#### Как сделать", "", *_steps_md(c.steps), ""]
            if c.scenarios:
                lines += ["#### Как это работает", "", *(f"- {user_rule(sc)}" for sc in c.scenarios), ""]
            for note in c.notes:
                lines += [*_quote("**Важно.**", note), ""]
    return lines


def render_guide_md(
    root: Path, composed: list[ComposedStory], solution: str | None, audience: str = "dev"
) -> str:
    """Guide of a solution. ``dev``: one section per composed story, in module
    dependency order, with tests, modules, menus and technical notes. ``user``:
    the end-user guide, chapters by section (:func:`guide_sections`)."""
    if audience not in AUDIENCES:
        raise ValueError(f"unknown audience {audience!r}")
    lines = _user_guide_md(composed) if audience == "user" else _dev_guide_md(root, composed, solution)
    return "\n".join(lines).rstrip() + "\n"


def _ref_dict(r: Ref) -> dict:
    return {"module": r.module, "kind": r.kind, "ident": r.ident}


def _scenario_dict(sc: Scenario) -> dict:
    return {
        "ident": sc.ident, "title": sc.title, "text": sc.text,
        "given": sc.given, "when": sc.when, "then": sc.then, "tests": list(sc.tests),
    }


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
        "section": story.section,
        "order": story.order,
        "menus": list(story.menus),
        "dev_notes": story.dev_notes,
        "intro": story.intro,
    }


def render_story_json(loc: Located, story: Story) -> str:
    return json.dumps(story_to_dict(loc, story), ensure_ascii=False, indent=2)


def composed_to_dict(c: ComposedStory) -> dict:
    """Developer view of a composed story (``--audience dev --format json``)."""
    return {
        "key": c.key,
        "module": c.module,
        "ident": c.ident,
        "section": c.section,
        "order": c.order,
        "title": c.title,
        "role": c.role,
        "goal": c.goal,
        "benefit": c.benefit,
        "intro": c.intro,
        "menus": list(c.menus),
        "steps": [_step_dict(st) for st in c.steps],
        "scenarios": [_scenario_dict(sc) for sc in c.scenarios],
        "modules": list(c.modules),
        "implements": [_ref_dict(r) for r in c.implements],
        "requirements": list(c.requirements),
        "notes": list(c.notes),
        "dev_notes": list(c.dev_notes),
    }


def user_story_dict(c: ComposedStory) -> dict:
    """End-user view of a composed story (``--audience user --format json``): the
    record an in-app help center loads. No tests, refs or technical notes."""
    return {
        "key": c.key,
        "section": c.section,
        "order": c.order,
        "title": c.title,
        "role": c.role,
        "goal": c.goal,
        "benefit": c.benefit,
        "intro": c.intro,
        "menus": list(c.menus),
        "steps": [_step_dict(st) for st in c.steps],
        "scenarios": [
            {"ident": sc.ident, "title": sc.title, "text": sc.text,
             "given": sc.given, "when": sc.when, "then": sc.then}
            for sc in c.scenarios
        ],
        "notes": list(c.notes),
        "modules": list(c.modules),
    }


def render_guide_json(composed: list[ComposedStory], solution: str | None, audience: str = "dev") -> str:
    """Guide JSON: ``{"format", "audience", "solution", "stories": [...]}``; user
    stories come in guide order (chapters), dev stories in dependency order."""
    if audience not in AUDIENCES:
        raise ValueError(f"unknown audience {audience!r}")
    if audience == "user":
        stories = [user_story_dict(c) for _, group in guide_sections(composed) for c in group]
    else:
        stories = [composed_to_dict(c) for c in composed]
    data = {"format": GUIDE_FORMAT, "audience": audience, "solution": solution, "stories": stories}
    return json.dumps(data, ensure_ascii=False, indent=2)
