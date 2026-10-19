"""In-app help export: ``static/help/stories.json`` per module (own stories, not composed)."""

import json
import sys
import unittest
from pathlib import Path

from pydacc.docs import loaded_stories
from pydacc.help import HELP_REL, help_freshness, render_help_json, screenshot_url
from tests.test_story_guide import CORE, RU, _guide_tree
from tests.test_stories import _cli, _module, _story, _tree, _write

sys.dont_write_bytecode = True

CORE_HELP = f"{CORE}/{HELP_REL}"
RU_HELP = f"{RU}/{HELP_REL}"
SOL_HELP = f"addons/solution/sol_base/{HELP_REL}"
STALE = ": stale help export — run `pydacc docs help`"

STORY_KEYS = [
    "key", "ident", "extends", "section", "order", "title", "intro", "role", "goal", "benefit",
    "menus", "steps", "scenarios", "replaces", "steps_after", "notes",
]


def _load(root: Path, rel: str) -> dict:
    return json.loads((root / rel).read_text(encoding="utf-8"))


class HelpContentTest(unittest.TestCase):
    def setUp(self):
        self.root = _guide_tree()
        self.code, self.out, self.err = _cli(self.root, "docs", "help")

    def test_writes_one_file_per_module_with_stories(self):
        self.assertEqual(self.code, 0, self.err)
        self.assertEqual(self.out, f"docs help: {CORE_HELP} written\ndocs help: {RU_HELP} written\n")
        self.assertEqual(sorted(p.relative_to(self.root).as_posix()
                                for p in self.root.glob(f"addons/*/*/{HELP_REL}")), [CORE_HELP, RU_HELP])

    def test_base_story(self):
        data = _load(self.root, CORE_HELP)
        self.assertEqual(list(data), ["format", "module", "stories"])
        self.assertEqual((data["format"], data["module"]), (1, "hrm_core"))
        self.assertEqual([s["ident"] for s in data["stories"]], ["0001", "0002", "0003", "0004", "0005"])
        s = data["stories"][0]
        self.assertEqual(list(s), STORY_KEYS)
        self.assertEqual(
            {k: s[k] for k in STORY_KEYS if k not in ("steps", "scenarios")},
            {
                "key": "hrm_core::story/0001", "ident": "0001", "extends": None,
                "section": "Работники", "order": 20, "title": "Приём на работу",
                "intro": "Вводный абзац.", "role": "кадровик", "goal": "оформить приём работника",
                "benefit": "он появился в штатной расстановке",
                "menus": ["hrm_core.menu_root", "hrm_core.menu_employees"],
                "replaces": {}, "steps_after": {}, "notes": ["Приём — только с даты."],
            },
        )
        self.assertEqual(s["steps"], [
            {"text": "Открыть «Сотрудники»", "screenshot": ""},
            {"text": "Открыть карточку", "screenshot": "/hrm_core/static/description/stories/hire_1.png"},
            {"text": "Нажать «Принять»", "screenshot": ""},
        ])
        self.assertEqual(s["scenarios"], [
            {"ident": "S1", "title": "Без назначения", "text": "Пояснение для пользователя."},
            {"ident": "S2", "title": "Кратко", "text": "Пояснение для пользователя."},
        ])
        self.assertEqual(data["stories"][4]["notes"], [])

    def test_user_audience_only(self):
        text = (self.root / CORE_HELP).read_text(encoding="utf-8")
        for word in ("tests", "given", "when", "then", "implements", "requirements", "dev_notes",
                     "Мастер — hrm.employee.wizard", "HRM-EFF-01", "test_hire"):
            self.assertNotIn(f'"{word}"' if word.isidentifier() else word, text)

    def test_extension(self):
        data = _load(self.root, RU_HELP)
        self.assertEqual(data["module"], "hrm_l10n_ru")
        (s,) = data["stories"]
        self.assertEqual(s, {
            "key": "hrm_l10n_ru::story/0001", "ident": "0001", "extends": "hrm_core::story/0001",
            "section": "", "order": 100, "title": "Приём на работу (РФ)", "intro": "",
            "role": "", "goal": "", "benefit": "",
            "menus": ["hrm_core.menu_employees", "hrm_l10n_ru.menu_ru"],
            "steps": [{"text": "Распечатать Т-1", "screenshot": ""}],
            "scenarios": [{"ident": "S3", "title": "Кратко", "text": "Пояснение для пользователя."}],
            "replaces": {"S2": {"ident": "S2", "title": "Кратко", "text": "Пояснение для пользователя."}},
            "steps_after": {"Открыть карточку": [{"text": "Заполнить СНИЛС", "screenshot": ""}]},
            "notes": ["Форма Т-1 — по постановлению Госкомстата № 1."],
        })

    def test_deterministic_layout(self):
        path = self.root / CORE_HELP
        first = path.read_bytes()
        data = json.loads(first)
        self.assertEqual(first.decode(), json.dumps(data, ensure_ascii=False, indent=1) + "\n")
        self.assertIn("Приём", first.decode())  # not \u-escaped
        path.unlink()
        _cli(self.root, "docs", "help")
        self.assertEqual(path.read_bytes(), first)

    def test_stories_ordered_by_ident(self):
        stories, _ = loaded_stories(self.root)
        items = [v for k, v in stories.items() if k[0] == "hrm_core"]
        self.assertEqual(render_help_json("hrm_core", list(reversed(items))),
                         (self.root / CORE_HELP).read_text(encoding="utf-8"))

    def test_rewrites_only_stale(self):
        self.assertEqual(_cli(self.root, "docs", "help")[:2], (0, ""))
        _story(self.root / RU, "0002", ' title="Своя", role="r", goal="g", benefit="b",'
               ' scenarios=(scenario("S1", "g", "w", "t"),),')
        self.assertEqual(_cli(self.root, "docs", "help")[:2], (0, f"docs help: {RU_HELP} written\n"))
        self.assertEqual([s["ident"] for s in _load(self.root, RU_HELP)["stories"]], ["0001", "0002"])


class ScreenshotUrlTest(unittest.TestCase):
    def test_url(self):
        self.assertEqual(screenshot_url("m", "static/img/a.png"), "/m/static/img/a.png")
        self.assertEqual(screenshot_url("m", "./static/img/../a.png"), "/m/static/a.png")
        self.assertEqual(screenshot_url("m", ""), "")


class HelpCheckTest(unittest.TestCase):
    def test_check_exit_codes(self):
        root = _tree()
        code, out, err = _cli(root, "docs", "help", "--check")
        self.assertEqual((code, out), (1, f"{CORE_HELP}\n{RU_HELP}\n"))
        self.assertIn("docs help --check: 2 stale", err)
        self.assertFalse((root / CORE_HELP).exists())  # --check writes nothing
        _cli(root, "docs", "help")
        code, out, err = _cli(root, "docs", "help", "--check")
        self.assertEqual((code, out), (0, ""))
        self.assertIn("docs help --check: fresh", err)
        _write(root / CORE_HELP, (root / CORE_HELP).read_text(encoding="utf-8").replace("Приём", "Найм"))
        self.assertEqual(_cli(root, "docs", "help", "--check")[:2], (1, f"{CORE_HELP}\n"))

    def test_orphan_file(self):
        root = _tree()
        _cli(root, "docs", "help")
        _write(root / SOL_HELP, "{}\n")
        self.assertEqual(_cli(root, "docs", "help", "--check")[:2], (1, f"{SOL_HELP}\n"))
        self.assertEqual(_cli(root, "docs", "help")[:2], (0, f"docs help: {SOL_HELP} deleted\n"))
        self.assertFalse((root / SOL_HELP).exists())
        self.assertFalse((root / SOL_HELP).parent.exists())  # empty static/help removed
        self.assertEqual(_cli(root, "docs", "help", "--check")[0], 0)

    def test_orphan_after_last_story_removed(self):
        root = _tree()
        _cli(root, "docs", "help")
        (root / RU / "stories" / "0001.py").unlink()
        self.assertEqual(_cli(root, "docs", "help", "--check")[:2], (1, f"{RU_HELP}\n"))

    def test_module_filter(self):
        root = _tree()
        self.assertEqual(_cli(root, "docs", "help", "--check", "--module", "hrm_l10n_ru")[:2],
                         (1, f"{RU_HELP}\n"))
        self.assertEqual(_cli(root, "docs", "help", "--module", "hrm_core")[:2],
                         (0, f"docs help: {CORE_HELP} written\n"))
        self.assertFalse((root / RU_HELP).exists())
        self.assertEqual(_cli(root, "docs", "help", "--check", "--module", "hrm_core")[0], 0)
        _write(root / SOL_HELP, "{}\n")
        self.assertEqual(_cli(root, "docs", "help", "--check", "--module", "sol_base")[:2],
                         (1, f"{SOL_HELP}\n"))
        self.assertEqual(_cli(root, "docs", "help", "--check", "--module", "sol_ru")[:2], (0, ""))

    def test_unknown_module(self):
        code, _, err = _cli(_tree(), "docs", "help", "--module", "nope")
        self.assertEqual(code, 2)
        self.assertIn("docs help: unknown module 'nope'", err)

    def test_broken_story_refuses_export(self):
        root = _tree()
        _write(root / RU / "stories" / "0002.py", "raise RuntimeError('boom')\n")
        code, out, err = _cli(root, "docs", "help")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("addons/country/hrm_l10n_ru/stories/0002.py: boom", err)
        self.assertFalse((root / RU_HELP).exists())
        # another module still exports
        self.assertEqual(_cli(root, "docs", "help", "--module", "hrm_core")[:2],
                         (0, f"docs help: {CORE_HELP} written\n"))


class HelpFreshnessTest(unittest.TestCase):
    def test_missing(self):
        root = _tree()
        self.assertEqual(help_freshness(root), [CORE_HELP + STALE, RU_HELP + STALE])
        code, _, err = _cli(root, "docs", "check")
        self.assertEqual(code, 1)
        self.assertIn(CORE_HELP + STALE, err)

    def test_fresh(self):
        root = _tree()
        _cli(root, "docs", "help")
        self.assertEqual(help_freshness(root), [])
        self.assertEqual(_cli(root, "docs", "check")[:2], (0, "docs check: fresh\n"))

    def test_stale(self):
        root = _tree()
        _cli(root, "docs", "help")
        ru = root / RU / "stories" / "0001.py"
        ru.write_text(ru.read_text().replace("Распечатать Т-1", "Распечатать приказ"))
        self.assertEqual(help_freshness(root), [RU_HELP + STALE])

    def test_orphan(self):
        root = _tree()
        _cli(root, "docs", "help")
        _write(root / SOL_HELP, "{}\n")
        self.assertEqual(help_freshness(root), [SOL_HELP + STALE])

    def test_no_stories_no_file(self):
        root = _tree()
        _module(root, "base", "plain")
        _cli(root, "docs", "help")
        self.assertEqual(help_freshness(root), [])
        self.assertFalse((root / "addons/base/plain/static").exists())


if __name__ == "__main__":
    unittest.main()
