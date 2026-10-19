"""Stories as an end-user guide: section/order/menus/notes, menu checks, audiences."""

import json
import sys
import unittest
from pathlib import Path

from pydacc.spec import DEFAULT_STORY_ORDER, Scenario, scenario, story
from pydacc.stories import (
    ComposedStory,
    compose,
    guide_sections,
    render_guide_json,
    render_guide_md,
    render_story_json,
    render_story_md,
    user_rule,
)
from pydacc.docs import loaded_stories
from tests.test_stories import _cli, _module, _problems, _story, _tree, _write

# Story files are rewritten within a second: never reuse a stale .pyc.
sys.dont_write_bytecode = True

CORE = "addons/base/hrm_core"
RU = "addons/country/hrm_l10n_ru"

MENUS_XML = """<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <menuitem id="menu_root" name="HRM">
        <menuitem id="hrm_core.menu_employees" name="Работники"/>
    </menuitem>
    <data>
        <record model="ir.ui.menu" id="menu_settings">
            <field name="name">Настройки</field>
        </record>
        <record model="ir.actions.act_window" id="action_not_a_menu"/>
    </data>
</odoo>
"""

RU_MENUS_XML = """<odoo>
    <menuitem id="menu_ru" name="РФ"/>
    <menuitem id="hrm_core.menu_ghost" name="override of a foreign id"/>
</odoo>
"""


def _base_story(body: str) -> str:
    return ' role="кадровик", goal="g", benefit="b", scenarios=(scenario("S1", "g", "w", "t"),),' + body


def _guide_tree() -> Path:
    """_tree() + menus + guide fields: four base stories in three sections and «Прочее»."""
    root = _tree()
    _write(root / CORE / "views" / "menus.xml", MENUS_XML)
    _write(root / RU / "views" / "menus.xml", RU_MENUS_XML)
    core = root / CORE / "stories" / "0001.py"
    core.write_text(core.read_text()
                    .replace('"создано назначение",', '"создано назначение.", title="Без назначения",')
                    .replace('requirements=("HRM-EFF-01",),',
                             'requirements=("HRM-EFF-01",), section="Работники", order=20,'
                             ' menus=("hrm_core.menu_root", "hrm_core.menu_employees"),'
                             ' notes="Приём — только с даты.", dev_notes="Мастер — hrm.employee.wizard.",'))
    ru = root / RU / "stories" / "0001.py"
    ru.write_text(ru.read_text().replace(
        'notes="Форма Т-1',
        'menus=("hrm_core.menu_employees", "hrm_l10n_ru.menu_ru"), dev_notes="СНИЛС — поле snils.",'
        ' notes="Форма Т-1'))
    _story(root / CORE, "0002", ' title="Подразделения",'
           + _base_story(' section="Структура", order=5, menus=("hrm_core.menu_settings",),'))
    _story(root / CORE, "0003", ' title="Увольнение",' + _base_story(' section="Работники", order=10,'))
    _story(root / CORE, "0004", ' title="Больничный",' + _base_story(' section="Неявки", order=10,'))
    _story(root / CORE, "0005", ' title="Разное",' + _base_story(' order=1,'))  # still last
    for path in root.glob("addons/*/*/stories/*.py"):
        _with_guide_texts(path)
    return root


GUIDE_TEXTS_HEADER = (
    "from pydacc.spec import scenario as _scenario\n"
    "def scenario(*args, **kwargs):\n"
    "    kwargs.setdefault('title', 'Кратко')\n"
    "    kwargs.setdefault('text', 'Пояснение для пользователя.')\n"
    "    return _scenario(*args, **kwargs)\n"
)


def _with_guide_texts(path: Path) -> None:
    """A story in the guide needs hand-written intro and scenario title/text:
    fill them where a fixture story has none (explicit values win)."""
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    last_import = max((i for i, line in enumerate(lines) if line.startswith(("from ", "import "))), default=-1)
    lines.insert(last_import + 1, GUIDE_TEXTS_HEADER)
    text = "".join(lines)
    if "intro=" not in text and "extends=" not in text:
        text = text.replace("section=", 'intro="Вводный абзац.", section=', 1)
    path.write_text(text)


class SpecFieldsTest(unittest.TestCase):
    def test_defaults_back_compat(self):
        s = story("m", "t")
        self.assertEqual((s.section, s.order, s.menus, s.dev_notes), ("", DEFAULT_STORY_ORDER, (), ""))
        self.assertEqual(DEFAULT_STORY_ORDER, 100)
        sc = Scenario("S1", "g", "w", "t", ("m.tests.test_x",))
        self.assertEqual(sc.title, "")
        self.assertEqual(scenario("S1", "g", "w", "t", title="Кратко").title, "Кратко")

    def test_new_fields(self):
        s = story("m", "t", section="Работники", order=5, menus=["m.menu_a"], dev_notes="d")
        self.assertEqual((s.section, s.order, s.menus, s.dev_notes), ("Работники", 5, ("m.menu_a",), "d"))
        hash(s)

    def test_types(self):
        with self.assertRaises(TypeError):
            story("m", "t", menus="m.menu_a")
        with self.assertRaises(TypeError):
            story("m", "t", order="1")
        with self.assertRaises(TypeError):
            story("m", "t", order=True)


class GuideFieldChecksTest(unittest.TestCase):
    def test_guide_tree_is_valid(self):
        self.assertEqual(_problems(_guide_tree()), "")

    def test_menus_need_section(self):
        root = _tree()
        _write(root / CORE / "views" / "menus.xml", MENUS_XML)
        _story(root / CORE, "0002", ' title="T",' + _base_story(' menus=("hrm_core.menu_root",),'))
        self.assertIn("hrm_core/stories/0002.py: menus need 'section' (the guide chapter)", _problems(root))

    def test_extension_menus_need_base_section(self):
        root = _tree()
        _write(root / RU / "views" / "menus.xml", RU_MENUS_XML)
        ru = root / RU / "stories" / "0001.py"
        ru.write_text(ru.read_text().replace('notes=', 'menus=("hrm_l10n_ru.menu_ru",), notes='))
        self.assertIn("hrm_l10n_ru/stories/0001.py: menus need 'section' in the base story"
                      " `hrm_core::story/0001`", _problems(root))

    def test_extension_must_not_set_section_or_order(self):
        for field in ('section="X",', "order=5,"):
            root = _tree()
            ru = root / RU / "stories" / "0001.py"
            ru.write_text(ru.read_text().replace('notes=', f'{field} notes='))
            self.assertIn("hrm_l10n_ru/stories/0001.py: extension must not set section/order"
                          " (taken from the base story)", _problems(root), field)

    def test_menu_resolution(self):
        root = _guide_tree()
        _write(root / CORE / "static" / "src" / "broken.xml", "<templates>")
        _story(root / CORE, "0006", ' title="M",' + _base_story(
            ' section="S", menus=("hrm_core.menu_root", "hrm_core.menu_employees", "hrm_core.menu_settings",'
            ' "hrm_core.menu_nope", "hrm_core.action_not_a_menu", "hrm_core.menu_ghost",'
            ' "hrm_l10n_ru.menu_ru", "base.menu_x", "menu_root", "a.b.c", "hrm_core.menu_root"),'))
        _with_guide_texts(root / CORE / "stories" / "0006.py")
        problems = [p for p in _problems(root).splitlines() if "0006.py" in p]
        rel = "addons/base/hrm_core/stories/0006.py"
        unparsable = " (unparsable: addons/base/hrm_core/static/src/broken.xml)"
        self.assertEqual(problems, [
            f"{rel}: menu 'hrm_core.menu_nope': not found in module 'hrm_core'{unparsable}",
            f"{rel}: menu 'hrm_core.action_not_a_menu': not found in module 'hrm_core'{unparsable}",
            f"{rel}: menu 'hrm_core.menu_ghost': not found in module 'hrm_core'{unparsable}",
            f"{rel}: menu 'hrm_l10n_ru.menu_ru': module 'hrm_l10n_ru' not in depends closure of 'hrm_core'",
            f"{rel}: menu 'base.menu_x': module 'base' not found under addons/",
            f"{rel}: menu 'menu_root': expected <module>.<menu xml id>",
            f"{rel}: menu 'a.b.c': expected <module>.<menu xml id>",
            f"{rel}: menu 'hrm_core.menu_root': duplicate",
        ])

    def test_extension_menu_of_dependency_resolves(self):
        root = _guide_tree()
        lone = _module(root, "country", "lone", ("base",))
        _write(lone / "menus.xml", '<odoo><menuitem id="menu_lone"/></odoo>')
        ru = root / RU / "stories" / "0001.py"
        ru.write_text(ru.read_text().replace('"hrm_l10n_ru.menu_ru")', '"hrm_l10n_ru.menu_ru", "lone.menu_lone")'))
        self.assertEqual(
            _problems(root),
            "addons/country/hrm_l10n_ru/stories/0001.py: menu 'lone.menu_lone':"
            " module 'lone' not in depends closure of 'hrm_l10n_ru'",
        )

    def test_check_cli(self):
        root = _guide_tree()
        _cli(root, "docs", "help")  # committed help export (test_story_help)
        self.assertEqual(_cli(root, "docs", "check")[:2], (0, "docs check: fresh\n"))
        _story(root / CORE, "0006", ' title="M",' + _base_story(' section="S", menus=("hrm_core.nope",),'))
        code, _, err = _cli(root, "docs", "check")
        self.assertEqual(code, 1)
        self.assertIn("menu 'hrm_core.nope': not found in module 'hrm_core'", err)


class ComposeGuideFieldsTest(unittest.TestCase):
    def test_menus_and_notes_merged(self):
        root = _guide_tree()
        (c,) = [c for c in compose(root, "sol_ru") if c.ident == "0001"]
        self.assertEqual((c.section, c.order), ("Работники", 20))
        self.assertEqual(c.menus, ("hrm_core.menu_root", "hrm_core.menu_employees", "hrm_l10n_ru.menu_ru"))
        self.assertEqual(c.notes, ("Приём — только с даты.", "Форма Т-1 — по постановлению Госкомстата № 1."))
        self.assertEqual(c.dev_notes, ("Мастер — hrm.employee.wizard.", "СНИЛС — поле snils."))
        self.assertEqual(c.key, "hrm_core::story/0001")
        (base,) = [c for c in compose(root, "sol_base") if c.ident == "0001"]
        self.assertEqual(base.menus, ("hrm_core.menu_root", "hrm_core.menu_employees"))
        self.assertEqual(base.dev_notes, ("Мастер — hrm.employee.wizard.",))

    def test_sections_order(self):
        sections = guide_sections(compose(_guide_tree(), "sol_ru"))
        self.assertEqual(
            [(name, [c.title for c in stories]) for name, stories in sections],
            [("Структура", ["Подразделения"]), ("Неявки", ["Больничный"]),
             ("Работники", ["Увольнение", "Приём на работу"]), ("Прочее", ["Разное"])],
        )


class UserGuideTest(unittest.TestCase):
    def setUp(self):
        self.root = _guide_tree()
        code, self.md, _ = _cli(self.root, "docs", "render", "--solution", "sol_ru", "--audience", "user")
        self.assertEqual(code, 0)

    def test_layout(self):
        self.assertTrue(self.md.startswith("# Руководство пользователя\n\n## Структура\n\n### Подразделения\n"))
        headings = [l for l in self.md.splitlines() if l.startswith("## ")]
        self.assertEqual(headings, ["## Структура", "## Неявки", "## Работники", "## Прочее"])
        self.assertLess(self.md.index("### Увольнение"), self.md.index("### Приём на работу"))
        self.assertIn(
            "### Приём на работу\n\n"
            "Вводный абзац.\n\n"
            "#### Как сделать\n\n"
            "1. Открыть «Сотрудники»\n"
            "2. Открыть карточку\n"
            "   ![](addons/base/hrm_core/static/description/stories/hire_1.png)\n"
            "3. Заполнить СНИЛС\n"
            "4. Нажать «Принять»\n"
            "5. Распечатать Т-1\n\n"
            "#### Как это работает\n\n"
            "- **Без назначения.** Пояснение для пользователя.\n"
            "- **Кратко.** Пояснение для пользователя.\n"
            "- **Кратко.** Пояснение для пользователя.\n\n"
            "> **Важно.** Приём — только с даты.\n\n"
            "> **Важно.** Форма Т-1 — по постановлению Госкомстата № 1.\n",
            self.md,
        )

    def test_nothing_technical_leaks(self):
        for leak in ("Тесты", "tests", "Модули", "Меню", "Для разработчика", "Мастер — hrm", "snils",
                     "HRM-EFF", "::", "sol_ru", "Дано", "menu_"):
            self.assertNotIn(leak, self.md)
        text = "\n".join(l for l in self.md.splitlines() if "![](" not in l)
        for module in ("hrm_core", "hrm_l10n_ru"):
            self.assertNotIn(module, text)

    def test_stories_without_new_fields(self):
        code, md, _ = _cli(_tree(), "docs", "render", "--solution", "sol_base", "--audience", "user")
        self.assertEqual(code, 0)
        self.assertTrue(md.startswith("# Руководство пользователя\n\n## Прочее\n\n### Приём на работу\n\n"
                                      "Кадровик: оформить приём работника"))
        self.assertIn("- **S1.** Если работник без назначения и кадровик принимает, то создано назначение.\n", md)
        self.assertNotIn("Важно", md)

    def test_rule_punctuation(self):
        sc = scenario("S1", "Работник уволен.", "СНИЛС не указан", "перевод отклоняется!", title="Уволен.")
        self.assertEqual(user_rule(sc),
                         "**Уволен.** Если работник уволен и СНИЛС не указан, то перевод отклоняется!")

    def test_multiline_note(self):
        c = ComposedStory("m", "0001", "T", "r", "g", "b", (), (), ("m",), (), (), notes=("a\nb",))
        self.assertIn("> **Важно.** a\n> b\n", render_guide_md(Path("."), [c], None, "user"))

    def test_unknown_audience(self):
        with self.assertRaises(ValueError):
            render_guide_md(self.root, [], None, "admin")
        with self.assertRaises(ValueError):
            render_guide_json([], None, "admin")
        code, _, err = _cli(self.root, "docs", "render", "--module", "hrm_core", "--audience", "user")
        self.assertEqual(code, 2)
        self.assertIn("--audience needs --solution", err)


class DevGuideTest(unittest.TestCase):
    def test_dev_md_adds_new_fields(self):
        root = _guide_tree()
        code, md, _ = _cli(root, "docs", "render", "--solution", "sol_ru")
        self.assertEqual(code, 0)
        self.assertEqual(md, _cli(root, "docs", "render", "--solution", "sol_ru", "--audience", "dev")[1])
        self.assertIn("#### S1 — Без назначения\n\n- **Дано:** работник без назначения", md)
        self.assertIn(
            "Приём — только с даты.\n\nФорма Т-1 — по постановлению Госкомстата № 1.\n\n"
            "**Для разработчика.** Мастер — hrm.employee.wizard.\n\n"
            "**Для разработчика.** СНИЛС — поле snils.\n\n"
            "Модули: `hrm_core`, `hrm_l10n_ru`\n\n"
            "Раздел: Работники (порядок 20)\n\n"
            "Меню: `hrm_core.menu_root`, `hrm_core.menu_employees`, `hrm_l10n_ru.menu_ru`\n",
            md,
        )
        self.assertIn("Модули: `hrm_core`\n\nРаздел: Структура (порядок 5)\n\nМеню: `hrm_core.menu_settings`\n", md)
        self.assertIn("Модули: `hrm_core`\n\nРаздел: Неявки (порядок 10)\n\n## ", md)

    def test_single_story_render(self):
        stories, _ = loaded_stories(_guide_tree())
        loc, base = stories[("hrm_core", "story", "0001")]
        md = render_story_md(_guide_tree(), loc, base)
        self.assertIn("- **Раздел:** Работники (порядок 20)\n", md)
        self.assertIn("## Меню\n\n- `hrm_core.menu_root`\n- `hrm_core.menu_employees`\n", md)
        self.assertTrue(md.endswith("## Примечания\n\nПриём — только с даты.\n\n"
                                    "## Для разработчика\n\nМастер — hrm.employee.wizard.\n"))
        data = json.loads(render_story_json(loc, base))
        self.assertEqual((data["section"], data["order"], data["menus"], data["dev_notes"]),
                         ("Работники", 20, ["hrm_core.menu_root", "hrm_core.menu_employees"],
                          "Мастер — hrm.employee.wizard."))
        self.assertEqual(data["scenarios"][0]["title"], "Без назначения")


USER_KEYS = {"key", "section", "order", "title", "role", "goal", "benefit", "intro", "menus", "steps", "scenarios",
             "notes", "modules"}
DEV_KEYS = USER_KEYS | {"module", "ident", "implements", "requirements", "dev_notes"}


class GuideJsonTest(unittest.TestCase):
    def _json(self, *extra: str) -> dict:
        code, out, _ = _cli(_guide_tree(), "docs", "render", "--solution", "sol_ru", "--format", "json", *extra)
        self.assertEqual(code, 0)
        return json.loads(out)

    def test_user_schema(self):
        data = self._json("--audience", "user")
        self.assertEqual(set(data), {"format", "audience", "solution", "stories"})
        self.assertEqual((data["format"], data["audience"], data["solution"]), (1, "user", "sol_ru"))
        self.assertEqual([s["title"] for s in data["stories"]],
                         ["Подразделения", "Больничный", "Увольнение", "Приём на работу", "Разное"])
        for s in data["stories"]:
            self.assertEqual(set(s), USER_KEYS)
            for sc in s["scenarios"]:
                self.assertEqual(set(sc), {"ident", "title", "text", "given", "when", "then"})
            for st in s["steps"]:
                self.assertEqual(set(st), {"text", "screenshot"})
        hire = data["stories"][3]
        self.assertEqual(hire["key"], "hrm_core::story/0001")
        self.assertEqual((hire["section"], hire["order"]), ("Работники", 20))
        self.assertEqual(hire["menus"], ["hrm_core.menu_root", "hrm_core.menu_employees", "hrm_l10n_ru.menu_ru"])
        self.assertEqual(hire["scenarios"][0]["title"], "Без назначения")
        self.assertEqual(hire["notes"], ["Приём — только с даты.", "Форма Т-1 — по постановлению Госкомстата № 1."])
        self.assertEqual(hire["modules"], ["hrm_core", "hrm_l10n_ru"])
        self.assertEqual(hire["steps"][1]["screenshot"],
                         "addons/base/hrm_core/static/description/stories/hire_1.png")
        self.assertEqual((data["stories"][4]["section"], data["stories"][4]["order"]), ("", 1))
        text = json.dumps(data, ensure_ascii=False)
        for leak in ("tests", "dev_notes", "snils", "HRM-EFF"):
            self.assertNotIn(leak, text)

    def test_dev_schema(self):
        data = self._json()
        self.assertEqual((data["format"], data["audience"], data["solution"]), (1, "dev", "sol_ru"))
        self.assertEqual(data, self._json("--audience", "dev"))
        for s in data["stories"]:
            self.assertEqual(set(s), DEV_KEYS)
            for sc in s["scenarios"]:
                self.assertEqual(set(sc), {"ident", "title", "text", "given", "when", "then", "tests"})
        hire = next(s for s in data["stories"] if s["key"] == "hrm_core::story/0001")
        self.assertEqual(hire["dev_notes"], ["Мастер — hrm.employee.wizard.", "СНИЛС — поле snils."])
        self.assertEqual(hire["scenarios"][0]["tests"], ["hrm_core.tests.test_hire.TestHire.test_hire"])
        self.assertEqual(hire["requirements"], ["HRM-EFF-01"])


if __name__ == "__main__":
    unittest.main()
