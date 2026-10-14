import tempfile
import unittest
from pathlib import Path

from pydacc.config import load_checks, load_snapshot_links


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
        self.assertFalse(checks[0].snapshot)

    def test_snapshot_flag_and_links(self):
        root = Path(tempfile.mkdtemp())
        (root / "pydacc.toml").write_text(
            '[snapshot]\nlink = ["run/env", "build"]\n\n'
            '[[checks]]\nname = "lint"\ncommand = ["true"]\nsnapshot = true\n'
        )
        self.assertTrue(load_checks(root)[0].snapshot)
        self.assertEqual(load_snapshot_links(root), ["run/env", "build"])

    def test_no_links_by_default(self):
        self.assertEqual(load_snapshot_links(Path(tempfile.mkdtemp())), [])


if __name__ == "__main__":
    unittest.main()
