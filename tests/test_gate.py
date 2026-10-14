import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pydacc.gate import Check, has_staged, index_snapshot, run


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


class GateTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_counts_passed_and_failed(self):
        verdict = run(self.root, [Check("ok", _py("pass")), Check("bad", _py("raise SystemExit(1)"))])
        self.assertEqual(verdict.passed, ["ok"])
        self.assertEqual(verdict.failed, ["bad"])
        self.assertFalse(verdict.ok)

    def test_failed_check_output_is_kept(self):
        # The agent learns the rule from the error: a failed check's output
        # must reach the verdict, not be swallowed by the gate.
        code = "import sys; print('why it failed'); print('detail', file=sys.stderr); raise SystemExit(1)"
        verdict = run(self.root, [Check("bad", _py(code))])
        self.assertIn("why it failed", verdict.output["bad"])
        self.assertIn("detail", verdict.output["bad"])

    def test_passed_check_output_is_not_kept(self):
        verdict = run(self.root, [Check("ok", _py("print('noise')"))])
        self.assertNotIn("ok", verdict.output)

    def test_env_reaches_checks(self):
        code = "import os; raise SystemExit(0 if os.environ.get('PYDACC_WORK') == 'w-x' else 1)"
        verdict = run(self.root, [Check("env", _py(code))], env={"PYDACC_WORK": "w-x"})
        self.assertTrue(verdict.ok)

    def test_on_start_called_per_check(self):
        started = []
        run(self.root, [Check("a", _py("pass")), Check("b", _py("pass"))], on_start=started.append)
        self.assertEqual(started, ["a", "b"])


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class SnapshotTest(unittest.TestCase):
    """Snapshot checks see what is committed: the index, not unstaged edits."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "t@example.com")
        _git(self.root, "config", "user.name", "t")
        (self.root / "f.txt").write_text("committed")
        _git(self.root, "add", "f.txt")
        _git(self.root, "commit", "-qm", "init")

    def test_has_staged(self):
        self.assertFalse(has_staged(self.root))
        (self.root / "f.txt").write_text("staged")
        _git(self.root, "add", "f.txt")
        self.assertTrue(has_staged(self.root))

    def test_snapshot_check_sees_index_not_worktree(self):
        (self.root / "f.txt").write_text("staged")
        _git(self.root, "add", "f.txt")
        (self.root / "f.txt").write_text("unstaged")
        read = "raise SystemExit(0 if open('f.txt').read() == '{}' else 1)"
        checks = [Check("snap", _py(read.format("staged")), snapshot=True),
                  Check("tree", _py(read.format("unstaged")))]
        with index_snapshot(self.root) as snap:
            verdict = run(self.root, checks, snapshot=snap)
        self.assertEqual(verdict.passed, ["snap", "tree"])

    def test_snapshot_check_without_snapshot_runs_in_root(self):
        (self.root / "f.txt").write_text("unstaged")
        code = "raise SystemExit(0 if open('f.txt').read() == 'unstaged' else 1)"
        self.assertTrue(run(self.root, [Check("snap", _py(code), snapshot=True)]).ok)

    def test_untracked_files_absent_links_present(self):
        (self.root / "untracked.txt").write_text("x")
        (self.root / "env").mkdir()
        (self.root / "env" / "bin").write_text("venv")
        with index_snapshot(self.root, ["env", "missing"]) as snap:
            self.assertFalse((snap / "untracked.txt").exists())
            self.assertEqual((snap / "env" / "bin").read_text(), "venv")
            self.assertFalse((snap / "missing").exists())
        self.assertFalse(snap.exists())

    def test_root_is_passed_to_snapshot_checks(self):
        code = f"import os; raise SystemExit(0 if os.environ['PYDACC_ROOT'] == {str(self.root)!r} else 1)"
        with index_snapshot(self.root) as snap:
            self.assertTrue(run(self.root, [Check("root", _py(code), snapshot=True)], snapshot=snap).ok)


if __name__ == "__main__":
    unittest.main()
