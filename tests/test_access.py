import tempfile
import unittest
from pathlib import Path

from pydacc.access import emit_docs, map_, refs_, where_


def _sample(root: Path) -> None:
    (root / "hrm_core").mkdir()
    (root / "hrm_core" / "models.py").write_text(
        'class Employee:\n    _name = "hrm.employee"\n    _fields = {"name": 1}\n'
    )


class MapTest(unittest.TestCase):
    def _tree(self) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "addons" / "base" / "hrm_core").mkdir(parents=True)
        (root / "addons" / "base" / "hrm_core" / "models.py").write_text(
            'class Employee:\n    _name = "hrm.employee"\n'
        )
        (root / "build" / "odoo" / "addons" / "mail").mkdir(parents=True)
        (root / "build" / "odoo" / "addons" / "mail" / "models.py").write_text(
            'class Message:\n    _name = "mail.message"\n'
        )
        return root

    def test_map_addons_only_by_default(self):
        root = self._tree()
        out = map_(root)
        self.assertIn("hrm.employee", out)
        self.assertNotIn("mail.message", out)

    def test_map_all_includes_vendored(self):
        root = self._tree()
        out = map_(root, addons_only=False)
        self.assertIn("hrm.employee", out)
        self.assertIn("mail.message", out)


class WhereTest(unittest.TestCase):
    def test_finds_model(self):
        root = Path(tempfile.mkdtemp())
        _sample(root)
        self.assertIn("hrm.employee", where_(root, "hrm_core/models.py"))

    def test_unknown_file(self):
        root = Path(tempfile.mkdtemp())
        self.assertIn("no introspected models", where_(root, "nope.py"))


class RefsTest(unittest.TestCase):
    def test_finds_term(self):
        root = Path(tempfile.mkdtemp())
        _sample(root)
        self.assertIn("models.py", refs_(root, "hrm.employee"))

    def test_missing_term(self):
        root = Path(tempfile.mkdtemp())
        self.assertIn("not found", refs_(root, "does-not-exist"))


class EmitTest(unittest.TestCase):
    def test_generates_docs(self):
        root = Path(tempfile.mkdtemp())
        _sample(root)
        docs = emit_docs(root)
        self.assertIn("# Agent rules", docs["AGENTS.md"])
        self.assertIn("@AGENTS.md", docs["QWEN.md"])

    def test_emit_includes_authored_rules(self):
        root = Path(tempfile.mkdtemp())
        (root / "docs" / "agents").mkdir(parents=True)
        (root / "docs" / "agents" / "rules.md").write_text("# My rules\n")
        docs = emit_docs(root)
        self.assertIn("# My rules", docs["AGENTS.md"])


if __name__ == "__main__":
    unittest.main()
