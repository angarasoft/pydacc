import tempfile
import unittest
from pathlib import Path

from pydacc.access import emit_docs, refs_, where_


def _sample(root: Path) -> None:
    (root / "hrm_core").mkdir()
    (root / "hrm_core" / "models.py").write_text(
        'class Employee:\n    _name = "hrm.employee"\n    _fields = {"name": 1}\n'
    )


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
        self.assertIn("hrm.employee", docs["AGENTS.md"])
        self.assertIn("@AGENTS.md", docs["QWEN.md"])


if __name__ == "__main__":
    unittest.main()
