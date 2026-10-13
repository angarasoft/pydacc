import tempfile
import unittest
from pathlib import Path

from pydacc.config import load_checks


class ConfigTest(unittest.TestCase):
    def test_absent_returns_none(self):
        self.assertIsNone(load_checks(Path(tempfile.mkdtemp())))

    def test_reads_checks(self):
        root = Path(tempfile.mkdtemp())
        (root / "pydacc.toml").write_text(
            '[[checks]]\nname = "foo"\ncommand = ["python3", "-c", "pass"]\n'
        )
        checks = load_checks(root)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].name, "foo")
        self.assertEqual(checks[0].command, ["python3", "-c", "pass"])


if __name__ == "__main__":
    unittest.main()
