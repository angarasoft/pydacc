import tempfile
import unittest
from pathlib import Path

from pydacc.introspect_ast import scan


class IntrospectTest(unittest.TestCase):
    def test_finds_odoo_models(self):
        root = Path(tempfile.mkdtemp())
        (root / "hrm_core").mkdir()
        (root / "hrm_core" / "models.py").write_text(
            '"""Module docstring."""\n'
            "\n"
            "class Employee:\n"
            '    """Class docstring — an ast.Expr, must not crash."""\n'
            '    _name = "hrm.employee"\n'
            '    _inherit = "res.partner"\n'
            '    _fields = {"name": 1, "age": 2}\n'
            "\n"
            "def helper():\n"
            "    pass\n"
        )
        models = scan(root)
        self.assertEqual(len(models), 1)
        model = models[0]
        self.assertEqual(model.name, "hrm.employee")
        self.assertEqual(model.klass, "Employee")
        self.assertEqual(model.module, "hrm_core")
        self.assertEqual(model.inherit, ("res.partner",))
        self.assertEqual(model.fields, ("name", "age"))


if __name__ == "__main__":
    unittest.main()
