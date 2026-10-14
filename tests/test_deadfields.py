import tempfile
import unittest
from pathlib import Path

from pydacc.deadfields import dead_fields


def _sample(root: Path) -> None:
    models = root / "addons" / "base" / "some_module" / "models"
    models.mkdir(parents=True)
    (models / "foo.py").write_text(
        "from odoo import fields, models\n"
        "\n"
        "class Foo(models.Model):\n"
        '    _name = "foo.model"\n'
        '    dead_field = fields.Char(string="Dead")\n'
        '    live_field = fields.Char(string="Live")\n'
    )


class DeadFieldsTest(unittest.TestCase):
    def test_unreferenced_field_is_dead(self):
        root = Path(tempfile.mkdtemp())
        _sample(root)
        views = root / "addons" / "base" / "some_module" / "views"
        views.mkdir(parents=True)
        (views / "foo_views.xml").write_text('<field name="live_field"/>\n')
        hits = {d.field for d in dead_fields(root)}
        self.assertIn("dead_field", hits)
        self.assertNotIn("live_field", hits)

    def test_field_referenced_in_python_is_live(self):
        root = Path(tempfile.mkdtemp())
        _sample(root)
        models = root / "addons" / "base" / "some_module" / "models"
        (models / "use.py").write_text(
            "class Use:\n"
            "    def f(self):\n"
            "        return self.live_field\n"
        )
        hits = {d.field for d in dead_fields(root)}
        self.assertIn("dead_field", hits)
        self.assertNotIn("live_field", hits)

    def test_std_fields_excluded(self):
        root = Path(tempfile.mkdtemp())
        models = root / "addons" / "base" / "some_module" / "models"
        models.mkdir(parents=True)
        (models / "foo.py").write_text(
            "from odoo import fields, models\n"
            "\n"
            "class Foo(models.Model):\n"
            '    _name = "foo.model"\n'
            '    name = fields.Char(string="Name")\n'
        )
        hits = {d.field for d in dead_fields(root)}
        self.assertNotIn("name", hits)


if __name__ == "__main__":
    unittest.main()
