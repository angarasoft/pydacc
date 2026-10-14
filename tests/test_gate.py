import sys
import tempfile
import unittest
from pathlib import Path

from pydacc.gate import Check, run


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


if __name__ == "__main__":
    unittest.main()
