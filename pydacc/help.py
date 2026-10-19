"""Per-module in-app help export: ``static/help/stories.json``.

Every module with stories carries its OWN stories (base stories and
extensions, not composed) as a committed JSON file that the Odoo module serves;
the help module composes them at runtime from the installed modules (README,
«In-app help export»). ``pydacc docs help`` writes the files, ``docs check``
reports stale, missing and orphan ones (the user.md freshness mechanism).

End-user audience: no tests, Дано/Когда/Тогда, implements, requirements or
dev_notes.
"""

from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass
from pathlib import Path

from .docs import Located, Stories, _fmt, _key_of, _load_all
from .spec import Scenario, Step, Story

HELP_DIR = "static/help"
HELP_FILENAME = "stories.json"
HELP_REL = f"{HELP_DIR}/{HELP_FILENAME}"   # inside the module dir
HELP_FORMAT = 1                           # bumped on incompatible layout changes
HELP_STALE = "stale help export — run `pydacc docs help`"


def _module_dir(loc: Located) -> Path:
    """``addons/<layer>/<module>`` (absolute) of a story file."""
    return loc.path.parent.parent


def screenshot_url(module: str, screenshot: str) -> str:
    """Module-relative path → URL Odoo serves it at: ``/<module>/<path>``; "" stays ""."""
    if not screenshot:
        return ""
    return f"/{module}/{posixpath.normpath(Path(screenshot).as_posix())}"


def _step(module: str, st: Step) -> dict:
    return {"text": st.text, "screenshot": screenshot_url(module, st.screenshot)}


def _scenario(sc: Scenario) -> dict:
    return {"ident": sc.ident, "title": sc.title, "text": sc.text}


def help_story_dict(loc: Located, story: Story) -> dict:
    """One story as written (an extension carries only its delta)."""
    module = loc.module
    return {
        "key": f"{module}::story/{loc.ident}",
        "ident": loc.ident,
        "extends": _fmt(_key_of(story.extends)) if story.extends is not None else None,
        "section": story.section,
        "order": story.order,
        "title": story.title,
        "intro": story.intro,
        "role": story.role,
        "goal": story.goal,
        "benefit": story.benefit,
        "menus": list(story.menus),
        "steps": [_step(module, st) for st in story.steps],
        "scenarios": [_scenario(sc) for sc in story.scenarios],
        "replaces": {ident: _scenario(sc) for ident, sc in story.replaces.items()},
        "steps_after": {
            anchor: [_step(module, st) for st in new] for anchor, new in story.steps_after.items()
        },
        "notes": [story.notes] if story.notes else [],
    }


def render_help_json(module: str, items: list[tuple[Located, Story]]) -> str:
    """``stories.json`` of one module: its stories ordered by ident."""
    data = {
        "format": HELP_FORMAT,
        "module": module,
        "stories": [help_story_dict(loc, s) for loc, s in sorted(items, key=lambda i: i[0].ident)],
    }
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


@dataclass(frozen=True)
class HelpExport:
    module: str
    path: Path               # absolute static/help/stories.json
    rel: str                 # relative to the scan root
    content: str | None      # expected content; None — the file must not exist

    def stale(self) -> bool:
        if self.content is None:
            return self.path.exists()
        return not self.path.is_file() or self.path.read_text(encoding="utf-8") != self.content


def _exports(root: Path, stories: Stories, module: str | None = None) -> list[HelpExport]:
    """Expected help files: one per module with stories, plus orphans to delete."""
    by_dir: dict[Path, tuple[str, list[tuple[Located, Story]]]] = {}
    for loc, story in stories.values():
        by_dir.setdefault(_module_dir(loc), (loc.module, []))[1].append((loc, story))
    exports = [
        HelpExport(name, mod_dir / HELP_REL, (mod_dir / HELP_REL).relative_to(root).as_posix(),
                   render_help_json(name, items))
        for mod_dir, (name, items) in by_dir.items()
    ]
    for path in root.glob(f"addons/*/*/{HELP_REL}"):
        mod_dir = path.parent.parent.parent
        if mod_dir not in by_dir:
            exports.append(HelpExport(mod_dir.name, path, path.relative_to(root).as_posix(), None))
    if module is not None:
        exports = [e for e in exports if e.module == module]
    return sorted(exports, key=lambda e: e.rel)


def _failed_story_modules(root: Path) -> tuple[Stories, set[str], list[str]]:
    """(stories, modules with a story that failed to load, load problems)."""
    located, _, _, stories, problems = _load_all(root)
    failed = {
        loc.module for loc in located
        if loc.kind == "story" and (loc.module, "story", loc.ident) not in stories
    }
    return stories, failed, problems


def help_freshness(root: Path) -> list[str]:
    """``docs check``: missing, outdated and orphan help files (load errors are
    reported by validate)."""
    _, _, _, stories, _ = _load_all(root)
    return [f"{e.rel}: {HELP_STALE}" for e in _exports(root, stories) if e.stale()]


class HelpError(Exception):
    """Export refused: unknown module or stories that do not load."""


def help_exports(root: Path, module: str | None = None) -> list[HelpExport]:
    """Expected help files (all modules or one); raises :class:`HelpError` when a
    story of an exported module cannot be loaded (its export would be wrong)."""
    if module is not None and not any(
        p.is_dir() for p in (root / "addons").glob(f"*/{module}")
    ):
        raise HelpError(f"unknown module {module!r}")
    stories, failed, problems = _failed_story_modules(root)
    if module is not None:
        failed &= {module}
    if failed:
        story_problems = [p for p in problems if any(f"/{m}/stories/" in p for m in failed)]
        raise HelpError("stories do not load:\n" + "\n".join(story_problems))
    return _exports(root, stories, module)


def write_help(exports: list[HelpExport]) -> list[tuple[str, str]]:
    """Write the stale files of :func:`help_exports`, delete orphans (and their
    emptied ``static/help``); returns ``[(rel, 'written'|'deleted')]``."""
    done: list[tuple[str, str]] = []
    for e in exports:
        if not e.stale():
            continue
        if e.content is None:
            e.path.unlink()
            if not any(e.path.parent.iterdir()):
                e.path.parent.rmdir()
            done.append((e.rel, "deleted"))
        else:
            e.path.parent.mkdir(parents=True, exist_ok=True)
            e.path.write_text(e.content, encoding="utf-8")
            done.append((e.rel, "written"))
    return done

