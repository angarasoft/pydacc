"""Истории в руководстве пользователя пишутся для людей: вводный абзац истории и
заголовок + текст каждого сценария — вручную (Дано/Когда/Тогда остаются для тестов)."""

import sys
import unittest

from pydacc.spec import scenario, story
from pydacc.stories import compose, render_guide_md, user_rule
from tests.test_story_guide import CORE, RU, _guide_tree
from tests.test_stories import _problems, _story, _tree

sys.dont_write_bytecode = True

GUIDE_SCENARIO = 'scenario("S1", "g", "w", "t", title="Кратко", text="Пояснение.")'


def _base(intro: str = 'intro="Вводный абзац.",', sc: str = GUIDE_SCENARIO, section: str = 'section="Работники",') -> str:
    return f' title="T", role="кадровик", goal="g", benefit="b", {intro} {section} scenarios=({sc},),'


class GuideTextChecksTest(unittest.TestCase):
    def _problems_of(self, root, name: str) -> list[str]:
        return [p for p in _problems(root).splitlines() if name in p]

    def test_story_in_guide_needs_intro(self):
        root = _tree()
        _story(root / CORE, "0007", _base(intro=""))
        self.assertEqual(self._problems_of(root, "0007.py"), [
            "addons/base/hrm_core/stories/0007.py: a story with 'section' needs 'intro' (user guide lead, written by hand)"])
        _story(root / CORE, "0007", _base())
        self.assertEqual(self._problems_of(root, "0007.py"), [])

    def test_scenarios_in_guide_need_title_and_text(self):
        root = _tree()
        _story(root / CORE, "0007", _base(sc='scenario("S1", "g", "w", "t")'))
        self.assertEqual(self._problems_of(root, "0007.py"), [
            "addons/base/hrm_core/stories/0007.py: scenario 'S1': a story in the guide needs 'title'",
            "addons/base/hrm_core/stories/0007.py: scenario 'S1': a story in the guide needs 'text'"])

    def test_story_outside_guide_needs_no_texts(self):
        root = _tree()
        _story(root / CORE, "0007", _base(intro="", sc='scenario("S1", "g", "w", "t")', section=""))
        self.assertEqual(self._problems_of(root, "0007.py"), [])

    def test_extension_scenarios_follow_base_section(self):
        root = _tree()
        _story(root / CORE, "0007", _base())
        ext = (' title="РФ", extends=ref("hrm_core", "story", "0007"),'
               ' scenarios=(scenario("S9", "g", "w", "t"),), replaces={"S1": scenario("S1", "g", "w", "t2")},')
        _story(root / RU, "0007", ext)
        self.assertEqual(self._problems_of(root, "hrm_l10n_ru/stories/0007.py"), [
            "addons/country/hrm_l10n_ru/stories/0007.py: scenario 'S9': a story in the guide needs 'title'",
            "addons/country/hrm_l10n_ru/stories/0007.py: scenario 'S9': a story in the guide needs 'text'",
            "addons/country/hrm_l10n_ru/stories/0007.py: scenario 'S1': a story in the guide needs 'title'",
            "addons/country/hrm_l10n_ru/stories/0007.py: scenario 'S1': a story in the guide needs 'text'"])

    def test_extension_must_not_set_intro(self):
        root = _tree()
        _story(root / CORE, "0007", _base())
        _story(root / RU, "0007", ' title="РФ", extends=ref("hrm_core", "story", "0007"), intro="Своё.",')
        self.assertIn("extension must not set intro (taken from the base story)",
                      _problems(root))


class GuideTextRenderTest(unittest.TestCase):
    def test_intro_and_texts_replace_templates(self):
        root = _guide_tree()
        md = render_guide_md(root, compose(root, None), None, audience="user")
        self.assertIn("### Увольнение\n\nВводный абзац.\n", md)
        self.assertIn("- **Кратко.** Пояснение для пользователя.\n", md)
        self.assertNotIn("Если g и w", md)

    def test_rule_falls_back_to_template_without_text(self):
        self.assertEqual(user_rule(scenario("S1", "работник уволен", "переводят", "отказ", title="Т")),
                         "**Т.** Если работник уволен и переводят, то отказ.")
        self.assertEqual(user_rule(scenario("S1", "g", "w", "t", title="Т", text="Свой текст")), "**Т.** Свой текст.")

    def test_story_intro_field(self):
        self.assertEqual(story("m", "t", intro="Абзац.").intro, "Абзац.")
        self.assertEqual(scenario("S1", "g", "w", "t").text, "")


if __name__ == "__main__":
    unittest.main()
