import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from pydacc.cli import main
from pydacc.docs import discover, load, loaded_stories, status_report, validate
from pydacc.spec import RFC_SECTIONS, Step, ref, story
from pydacc.stories import compose, render_guide_md, render_story_json, render_story_md

# Story files are rewritten within a second: never reuse a stale .pyc.
sys.dont_write_bytecode = True

SECTIONS_PY = "sections=(" + ", ".join(f'Section("{t}", "body")' for t in RFC_SECTIONS) + ")"

BASE_STORY = '''
    title="Приём на работу",
    role="кадровик",
    goal="оформить приём работника",
    benefit="он появился в штатной расстановке",
    implements=(ref("hrm_core", "plan", "0001"), ref("hrm_core", "rfc")),
    requirements=("HRM-EFF-01",),
    steps=(
        "Открыть «Сотрудники»",
        step("Открыть карточку", screenshot="static/description/stories/hire_1.png"),
        "Нажать «Принять»",
    ),
    scenarios=(
        scenario("S1", "работник без назначения", "кадровик принимает", "создано назначение",
                 tests=("hrm_core.tests.test_hire.TestHire.test_hire",)),
        scenario("S2", "дата приёма в прошлом", "кадровик принимает", "приём разрешён",
                 tests=("hrm_core.tests.test_hire",)),
    ),
'''

RU_STORY = '''
    title="Приём на работу (РФ)",
    extends=ref("hrm_core", "story", "0001"),
    scenarios=(
        scenario("S3", "нет СНИЛС", "кадровик принимает", "предупреждение о СНИЛС",
                 tests=("hrm_l10n_ru.tests.test_snils.TestSnils.test_warn",)),
    ),
    replaces={
        "S2": scenario("S2", "дата приёма в прошлом", "кадровик принимает", "нужен приказ Т-1",
                       tests=("hrm_l10n_ru.tests.test_snils.TestSnils",)),
    },
    steps_after={"Открыть карточку": ["Заполнить СНИЛС"]},
    steps=("Распечатать Т-1",),
    notes="Форма Т-1 — по постановлению Госкомстата № 1.",
'''


def _module(root: Path, layer: str, name: str, depends: tuple[str, ...] = ()) -> Path:
    mod = root / "addons" / layer / name
    mod.mkdir(parents=True)
    (mod / "__manifest__.py").write_text(
        "# -*- coding: utf-8 -*-\n" f"{{'name': '{name}', 'version': '1.0', 'depends': {list(depends)!r}}}\n"
    )
    return mod


def _story(mod: Path, ident: str, body: str, module: str | None = None) -> None:
    d = mod / "stories"
    d.mkdir(exist_ok=True)
    (d / f"{ident}.py").write_text(
        "from pydacc.spec import story, scenario, step, ref\n"
        f'STORY = story(module="{module or mod.name}",{body})\n'
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _tree() -> Path:
    """hrm_core (base story) ← hrm_l10n_ru (extension); sol_ru / sol_base solutions."""
    root = Path(tempfile.mkdtemp())
    core = _module(root, "base", "hrm_core", ("base",))
    _write(core / "plan" / "0001.py",
           "from pydacc.spec import plan, req, Section, Status\n"
           f'PLAN = plan(module="hrm_core", title="P", status=Status.DRAFT, {SECTIONS_PY},'
           ' requirements=(req("HRM-EFF-01", "Приём", why="ТК РФ", affects="назначения",'
           ' used_in=("Т-1",)),))\n')
    _write(core / "__rfc__.py",
           "from pydacc.spec import rfc, Section, Status\n"
           f'RFC = rfc(module="hrm_core", title="Core", status=Status.DRAFT, {SECTIONS_PY},'
           ' requirements=())\n')
    _write(core / "tests" / "test_hire.py",
           "class TestHire:\n"
           "    def test_hire(self):\n        pass\n"
           "    async def test_async(self):\n        pass\n")
    _write(core / "static" / "description" / "stories" / "hire_1.png", "png")
    _story(core, "0001", BASE_STORY)
    ru = _module(root, "country", "hrm_l10n_ru", ("hrm_core",))
    _write(ru / "tests" / "test_snils.py", "class TestSnils:\n    def test_warn(self):\n        pass\n")
    _story(ru, "0001", RU_STORY)
    _module(root, "solution", "sol_ru", ("hrm_l10n_ru",))
    _module(root, "solution", "sol_base", ("hrm_core",))
    return root


def _cli(root: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    cwd = os.getcwd()
    os.chdir(root)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
    finally:
        os.chdir(cwd)
    return code, out.getvalue(), err.getvalue()


def _problems(root: Path) -> str:
    return "\n".join(validate(root))


class SpecTest(unittest.TestCase):
    def test_plain_strings_are_steps(self):
        s = story("m", "t", steps=("a", Step("b", "x.png")), steps_after={"a": "c"})
        self.assertEqual(s.steps, (Step("a"), Step("b", "x.png")))
        self.assertEqual(s.steps_after, {"a": (Step("c"),)})
        self.assertEqual(s.kind, "story")

    def test_extends_must_be_ref(self):
        with self.assertRaises(TypeError):
            story("m", "t", extends="hrm_core::story/0001")
        self.assertEqual(story("m", "t", extends=ref("x", "story", "1")).extends, ref("x", "story", "1"))

    def test_story_is_hashable(self):
        hash(story("m", "t", replaces={}, steps_after={"a": ["b"]}))


class RegistryTest(unittest.TestCase):
    def test_discover_and_ident_from_filename(self):
        root = _tree()
        locs = [l for l in discover(root) if l.kind == "story"]
        self.assertEqual({(l.module, l.ident) for l in locs}, {("hrm_core", "0001"), ("hrm_l10n_ru", "0001")})
        loc = next(l for l in locs if l.module == "hrm_core")
        self.assertEqual(load(root, loc).ident, "0001")

    def test_exactly_one_story(self):
        root = _tree()
        _write(root / "addons/base/hrm_core/stories/0002.py", "X = 1\n")
        self.assertIn("expected exactly one Story, found 0", _problems(root))

    def test_status_and_list(self):
        root = _tree()
        self.assertRegex(status_report(root), r"hrm_core::story/0001\s+story\s+Приём на работу")
        code, out, _ = _cli(root, "docs", "list")
        self.assertEqual(code, 0)
        self.assertIn("addons/base/hrm_core/stories/0001.py\tstory\tbase\thrm_core", out)

    def test_render_single_story(self):
        root = _tree()
        stories, _ = loaded_stories(root)
        loc, ext = stories[("hrm_l10n_ru", "story", "0001")]
        md = render_story_md(root, loc, ext)
        self.assertIn("- **Расширяет:** `hrm_core::story/0001`", md)
        self.assertIn("## Заменяет сценарии", md)
        self.assertIn("После «Открыть карточку»:", md)
        self.assertTrue(md.endswith("## Примечания\n\nФорма Т-1 — по постановлению Госкомстата № 1.\n"))
        data = json.loads(render_story_json(loc, ext))
        self.assertEqual(data["extends"], {"module": "hrm_core", "kind": "story", "ident": "0001"})
        self.assertEqual(data["steps_after"]["Открыть карточку"][0]["text"], "Заполнить СНИЛС")
        code, out, _ = _cli(root, "docs", "render", "--module", "hrm_core")
        self.assertEqual(code, 0)
        self.assertIn("Как кадровик я хочу оформить приём работника", out)


class ComposeTest(unittest.TestCase):
    def test_superposition(self):
        root = _tree()
        (c,) = compose(root, "sol_ru")
        self.assertEqual(c.title, "Приём на работу")
        self.assertEqual(c.role, "кадровик")
        self.assertEqual([s.ident for s in c.scenarios], ["S1", "S2", "S3"])
        self.assertEqual(c.scenarios[1].then, "нужен приказ Т-1")
        self.assertEqual(
            [s.text for s in c.steps],
            ["Открыть «Сотрудники»", "Открыть карточку", "Заполнить СНИЛС", "Нажать «Принять»", "Распечатать Т-1"],
        )
        self.assertEqual(c.steps[1].screenshot, "addons/base/hrm_core/static/description/stories/hire_1.png")
        self.assertEqual(c.modules, ("hrm_core", "hrm_l10n_ru"))
        self.assertEqual(c.requirements, ("HRM-EFF-01",))
        self.assertEqual(c.notes, ("Форма Т-1 — по постановлению Госкомстата № 1.",))

    def test_extension_of_extension_order(self):
        root = _tree()
        x = _module(root, "country", "hrm_x", ("hrm_l10n_ru",))
        _story(x, "0001", '''
            title="X", extends=ref("hrm_l10n_ru", "story", "0001"),
            steps_after={"Открыть карточку": ["Шаг X"], "Заполнить СНИЛС": ["Проверить СНИЛС"]},
            scenarios=(scenario("S4", "g", "w", "t"),),
        ''')
        # a later extension anchored on the base step reads after every earlier
        # insertion there, nested ones included
        y = _module(root, "country", "hrm_y", ("hrm_x",))
        _story(y, "0001", '''
            title="Y", extends=ref("hrm_core", "story", "0001"),
            steps_after={"Открыть карточку": ["Шаг Y"]},
        ''')
        self.assertEqual(_problems(root), "")
        (c,) = compose(root, None)
        self.assertEqual(
            [s.text for s in c.steps],
            ["Открыть «Сотрудники»", "Открыть карточку", "Заполнить СНИЛС", "Проверить СНИЛС", "Шаг X",
             "Шаг Y", "Нажать «Принять»", "Распечатать Т-1"],
        )
        self.assertEqual([s.ident for s in c.scenarios], ["S1", "S2", "S3", "S4"])
        self.assertEqual(c.modules, ("hrm_core", "hrm_l10n_ru", "hrm_x", "hrm_y"))

    def test_solution_scope(self):
        root = _tree()
        (c,) = compose(root, "sol_base")
        self.assertEqual(c.modules, ("hrm_core",))
        self.assertEqual([s.ident for s in c.scenarios], ["S1", "S2"])
        self.assertEqual(c.scenarios[1].then, "приём разрешён")

    def test_unknown_solution(self):
        with self.assertRaises(ValueError):
            compose(_tree(), "nope")
        code, _, err = _cli(_tree(), "docs", "render", "--solution", "nope")
        self.assertEqual(code, 2)
        self.assertIn("unknown solution", err)

    def test_render_guide_cli(self):
        root = _tree()
        code, out, _ = _cli(root, "docs", "render", "--solution", "sol_base")
        self.assertEqual(code, 0)
        self.assertNotIn("hrm_l10n_ru", out)
        self.assertNotIn("СНИЛС", out)
        code, out, _ = _cli(root, "docs", "render", "--solution", "sol_ru")
        self.assertEqual(code, 0)
        self.assertIn("# Руководство пользователя: sol_ru", out)
        self.assertIn("## Приём на работу\n\nКак кадровик я хочу оформить приём работника,"
                      " чтобы он появился в штатной расстановке.", out)
        self.assertIn("2. Открыть карточку\n   ![](addons/base/hrm_core/static/description/stories/hire_1.png)\n"
                      "3. Заполнить СНИЛС", out)
        self.assertIn("#### S3\n\n- **Дано:** нет СНИЛС\n- **Когда:** кадровик принимает\n"
                      "- **Тогда:** предупреждение о СНИЛС", out)
        self.assertIn("- **Тесты:** [`hrm_core.tests.test_hire.TestHire.test_hire`]"
                      "(addons/base/hrm_core/tests/test_hire.py)", out)
        self.assertIn("Форма Т-1 — по постановлению Госкомстата № 1.\n\nМодули: `hrm_core`, `hrm_l10n_ru`", out)
        code, out, _ = _cli(root, "docs", "render", "--solution", "sol_ru", "--format", "json")
        data = json.loads(out)
        self.assertEqual(data["solution"], "sol_ru")
        self.assertEqual(data["stories"][0]["modules"], ["hrm_core", "hrm_l10n_ru"])

    def test_guide_title_without_solution(self):
        root = _tree()
        (c,) = compose(root, None)
        md = render_guide_md(root, [c], None)
        self.assertTrue(md.startswith("# Руководство пользователя\n"))


class ValidateStoriesTest(unittest.TestCase):
    """Каждое правило — падающий и проходящий случай; проходящий — `_tree()`."""

    def test_valid_tree(self):
        self.assertEqual(validate(_tree()), [])
        code, out, _ = _cli(_tree(), "docs", "check")
        self.assertEqual((code, out), (0, "docs check: fresh\n"))

    # a) shape
    def test_base_needs_role_and_scenario(self):
        root = _tree()
        _story(root / "addons/base/hrm_core", "0002", ' title="T", goal="g", benefit="b",')
        problems = _problems(root)
        self.assertIn("hrm_core/stories/0002.py: empty 'role'", problems)
        self.assertIn("0002.py: base story needs at least one scenario", problems)

    def test_extension_shape(self):
        root = _tree()
        _story(root / "addons/country/hrm_l10n_ru", "0002",
               ' title="", role="r", extends=ref("hrm_core", "story", "0001"),')
        _story(root / "addons/base/hrm_core", "0003",
               ' title="T", role="r", goal="g", benefit="b", scenarios=(scenario("S1", "g", "w", "t"),),'
               ' steps_after={"a": "b"},')
        problems = _problems(root)
        self.assertIn("hrm_l10n_ru/stories/0002.py: empty 'title'", problems)
        self.assertIn("0002.py: extension must not set role/goal/benefit", problems)
        self.assertIn("hrm_core/stories/0003.py: replaces/steps_after need extends", problems)

    def test_module_mismatch(self):
        root = _tree()
        _story(root / "addons/country/hrm_l10n_ru", "0002",
               ' title="T", extends=ref("hrm_core", "story", "0001"),', module="other")
        self.assertIn("content module 'other' != dir 'hrm_l10n_ru'", _problems(root))

    # b) scenario idents
    def test_duplicate_scenario_ident(self):
        root = _tree()
        _story(root / "addons/base/hrm_core", "0002",
               ' title="T", role="r", goal="g", benefit="b",'
               ' scenarios=(scenario("S1", "g", "w", "t"), scenario("S1", "g", "w", "")),')
        problems = _problems(root)
        self.assertIn("0002.py: scenario 'S1': duplicate ident", problems)
        self.assertIn("0002.py: scenario 'S1': empty 'then'", problems)

    def test_extension_collides_with_base(self):
        root = _tree()
        ru = root / "addons/country/hrm_l10n_ru/stories/0001.py"
        ru.write_text(ru.read_text().replace('scenario("S3"', 'scenario("S1"')
                      .replace('"S2": scenario("S2"', '"S2": scenario("S9"'))
        problems = _problems(root)
        self.assertIn("scenario 'S1' collides with composed base `hrm_core::story/0001` (use replaces)", problems)
        self.assertIn("replaces 'S2': scenario ident 'S9' must equal the key", problems)

    def test_sibling_extensions_collide(self):
        root = _tree()
        other = _module(root, "country", "hrm_other", ("hrm_core",))
        _story(other, "0001", ' title="O", extends=ref("hrm_core", "story", "0001"),'
                              ' scenarios=(scenario("S3", "g", "w", "t"),),')
        self.assertIn("composed story `hrm_core::story/0001`: duplicate scenario 'S3'", _problems(root))

    # c) extends
    def test_extends_missing_and_not_story(self):
        root = _tree()
        ru = root / "addons/country/hrm_l10n_ru"
        _story(ru, "0002", ' title="T", extends=ref("hrm_core", "story", "0009"),')
        _story(ru, "0003", ' title="T", extends=ref("hrm_core", "plan", "0001"),')
        _story(ru, "0004", ' title="T", extends=ref("hrm_l10n_ru", "story", "0001"),')
        problems = _problems(root)
        self.assertIn("0002.py: extends `hrm_core::story/0009`: missing story", problems)
        self.assertIn("0003.py: extends `hrm_core::plan/0001`: not a story", problems)
        self.assertIn("0004.py: extends `hrm_l10n_ru::story/0001`: must extend a story of another module", problems)

    def test_extends_outside_depends(self):
        root = _tree()
        lone = _module(root, "country", "lone", ("base",))
        _story(lone, "0001", ' title="T", extends=ref("hrm_core", "story", "0001"),')
        self.assertIn("lone/stories/0001.py: extends `hrm_core::story/0001`: module 'hrm_core'"
                      " is not in the depends closure of 'lone'", _problems(root))

    def test_transitive_depends_ok(self):
        root = _tree()
        deep = _module(root, "country", "deep", ("hrm_l10n_ru",))  # hrm_core only transitively
        _story(deep, "0001", ' title="T", extends=ref("hrm_core", "story", "0001"),'
                             ' scenarios=(scenario("S7", "g", "w", "t"),),')
        self.assertEqual(_problems(root), "")

    def test_base_cannot_extend_country(self):
        root = _tree()
        b = _module(root, "base", "hrm_b", ("hrm_l10n_ru",))
        _story(b, "0001", ' title="T", extends=ref("hrm_l10n_ru", "story", "0001"),')
        self.assertIn("hrm_b/stories/0001.py: extends `hrm_l10n_ru::story/0001`:"
                      " a base-layer story cannot extend a country-layer story", _problems(root))

    def test_extends_cycle(self):
        root = Path(tempfile.mkdtemp())
        a = _module(root, "country", "a", ("b",))
        b = _module(root, "country", "b", ("a",))
        _story(a, "0001", ' title="A", extends=ref("b", "story", "0001"),')
        _story(b, "0001", ' title="B", extends=ref("a", "story", "0001"),')
        problems = _problems(root)
        self.assertIn("story extends cycle:", problems)
        self.assertEqual(compose(root, None), [])

    # d) replaces / steps_after against the composed base
    def test_replaces_and_steps_after_unknown(self):
        root = _tree()
        ru = root / "addons/country/hrm_l10n_ru/stories/0001.py"
        ru.write_text(ru.read_text().replace('"S2": scenario("S2"', '"S8": scenario("S8"')
                      .replace('{"Открыть карточку":', '{"Открыть карточку ":'))
        problems = _problems(root)
        self.assertIn("replaces 'S8': no such scenario in composed base `hrm_core::story/0001`", problems)
        self.assertIn("steps_after 'Открыть карточку ': no such step in composed base", problems)

    # e) implements / requirements
    def test_implements_and_requirements(self):
        root = _tree()
        core = root / "addons/base/hrm_core/stories/0001.py"
        core.write_text(core.read_text()
                        .replace('ref("hrm_core", "rfc")', 'ref("hrm_core", "rfc", "0042"), ref("hrm_core", "story", "0001")')
                        .replace('("HRM-EFF-01",)', '("HRM-EFF-01", "HRM-EFF-99")'))
        problems = _problems(root)
        self.assertIn("implements `hrm_core::rfc/0042`: missing doc", problems)
        self.assertIn("implements `hrm_core::story/0001`: not an rfc/plan doc", problems)
        self.assertIn("requirement 'HRM-EFF-99': not found in implemented docs", problems)
        self.assertNotIn("'HRM-EFF-01'", problems)

    def test_requirement_without_implements(self):
        root = _tree()
        core = root / "addons/base/hrm_core/stories/0001.py"
        core.write_text(core.read_text().replace(
            'implements=(ref("hrm_core", "plan", "0001"), ref("hrm_core", "rfc")),', ""))
        self.assertIn("requirement 'HRM-EFF-01': not found in implemented docs", _problems(root))

    # f) test ids
    def test_test_ids(self):
        root = _tree()
        cases = {
            "hrm_core.tests.test_nope": "no file addons/base/hrm_core/tests/test_nope.py",
            "hrm_core.tests.test_hire.Nope": "no class 'Nope' in addons/base/hrm_core/tests/test_hire.py",
            "hrm_core.tests.test_hire.TestHire.test_nope": "no method 'TestHire.test_nope'",
            "hrm_core.test_hire": "malformed test id",
            "ghost.tests.test_x": "no module 'ghost'",
        }
        tests = ", ".join(f'"{t}"' for t in [*cases, "hrm_core.tests.test_hire.TestHire.test_async"])
        _story(root / "addons/base/hrm_core", "0002",
               ' title="T", role="r", goal="g", benefit="b",'
               f' scenarios=(scenario("S1", "g", "w", "t", tests=({tests},)),),')
        problems = _problems(root)
        for test_id, message in cases.items():
            self.assertIn(f"0002.py: scenario 'S1': test '{test_id}': {message}", problems)
        self.assertNotIn("test_async", problems)

    # g) screenshots
    def test_screenshots(self):
        root = _tree()
        _write(root / "addons/base/hrm_core/../outside.png", "x")
        _story(root / "addons/base/hrm_core", "0002",
               ' title="T", role="r", goal="g", benefit="b", scenarios=(scenario("S1", "g", "w", "t"),),'
               ' steps=(step("a", "static/none.png"), step("b", "../outside.png"),'
               ' step("c", "static/description/stories/hire_1.png")),')
        problems = _problems(root)
        self.assertIn("0002.py: step 'a': screenshot 'static/none.png' not found in addons/base/hrm_core", problems)
        self.assertIn("0002.py: step 'b': screenshot '../outside.png' not found", problems)
        self.assertNotIn("step 'c'", problems)

    def test_screenshot_in_inserted_steps(self):
        root = _tree()
        ru = root / "addons/country/hrm_l10n_ru/stories/0001.py"
        ru.write_text(ru.read_text().replace('["Заполнить СНИЛС"]', '[step("Заполнить СНИЛС", "snils.png")]'))
        self.assertIn("step 'Заполнить СНИЛС': screenshot 'snils.png' not found in addons/country/hrm_l10n_ru",
                      _problems(root))
        _write(root / "addons/country/hrm_l10n_ru/snils.png", "png")
        self.assertEqual(_problems(root), "")
        (c,) = compose(root, "sol_ru")
        self.assertEqual(c.steps[2].screenshot, "addons/country/hrm_l10n_ru/snils.png")

    def test_check_cli_fails_on_story_problem(self):
        root = _tree()
        _story(root / "addons/base/hrm_core", "0002", ' title="T",')
        code, _, err = _cli(root, "docs", "check")
        self.assertEqual(code, 1)
        self.assertIn("empty 'role'", err)


if __name__ == "__main__":
    unittest.main()
