import tempfile
import unittest
from pathlib import Path

from pydacc import journal

TREE = "0123456789abcdef0123456789abcdef01234567"
COMMIT = "792a883f589e41a3aa1051ca1528bdc0b58d05c0"


class ParseTest(unittest.TestCase):
    def test_round_trip(self):
        text = (
            "[[events]]\n"
            'event = "started"\nwork = "w-001"\nat = "2026-09-11T03:15:00Z"\n'
            "[[events]]\n"
            'event = "gate"\nwork = "w-001"\nat = "2026-09-11T03:15:00Z"\n'
            'gate = "commit"\n'
            f'tree = "{TREE}"\n'
            'passed = "11"\ntotal = "12"\nskipped = "external names"\nattacks = "24"\n'
            "[[events]]\n"
            'event = "landed"\nwork = "w-001"\nat = "2026-09-11T03:15:00Z"\n'
            f'commit = "{COMMIT}"\ntree = "{TREE}"\n'
        )
        records = journal.parse(text)
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["event"], "started")
        self.assertEqual(records[2]["commit"], COMMIT)

    def test_render_parses_back(self):
        record = {
            "event": "landed",
            "work": "w-001",
            "at": "2026-09-11T03:15:00Z",
            "commit": TREE,
            "tree": TREE,
        }
        self.assertEqual(journal.parse(journal.render(record)), [record])

    def test_unknown_event(self):
        with self.assertRaises(journal.JournalError):
            journal.parse('[[events]]\nevent = "begun"\nwork = "w-001"\nat = "2026-09-11T03:15:00Z"\n')

    def test_extra_field(self):
        with self.assertRaises(journal.JournalError):
            journal.parse('[[events]]\nevent = "started"\nwork = "w-001"\nat = "2026-09-11T03:15:00Z"\nowner = "x"\n')

    def test_bad_hash(self):
        with self.assertRaises(journal.JournalError):
            journal.parse(
                f'[[events]]\nevent = "landed"\nwork = "w-001"\nat = "2026-09-11T03:15:00Z"\ncommit = "XYZ"\ntree = "{TREE}"\n'
            )

    def test_bad_timestamp(self):
        with self.assertRaises(journal.JournalError):
            journal.parse('[[events]]\nevent = "started"\nwork = "w-001"\nat = "yesterday"\n')

    def test_self_commit_requires_gate_evidence(self):
        with self.assertRaises(journal.JournalError):
            journal.parse(
                f'[[events]]\nevent = "landed"\nwork = "w-001"\nat = "2026-09-11T03:15:00Z"\ncommit = "self"\ntree = "{TREE}"\nevidence = "history"\n'
            )

    def test_self_commit_ok_with_gate(self):
        journal.parse(
            f'[[events]]\nevent = "landed"\nwork = "w-001"\nat = "2026-09-11T03:15:00Z"\ncommit = "self"\ntree = "{TREE}"\n'
        )

    def test_repeated_key(self):
        with self.assertRaises(journal.JournalError):
            journal.parse(
                '[[events]]\nevent = "started"\nevent = "started"\nwork = "w-001"\nat = "2026-09-11T03:15:00Z"\n'
            )


class AppendTest(unittest.TestCase):
    def test_append_validates_and_writes(self):
        root = Path(tempfile.mkdtemp())
        path = root / "journal.toml"
        journal.append(path, [
            {"event": "gate", "work": "w-001", "at": "2026-09-11T03:15:00Z",
             "gate": "commit", "tree": TREE, "passed": "1", "total": "1", "attacks": "0"},
            {"event": "landed", "work": "w-001", "at": "2026-09-11T03:15:00Z",
             "commit": "self", "tree": TREE},
        ])
        records = journal.parse(path.read_text(encoding="utf-8"))
        self.assertEqual([r["event"] for r in records], ["gate", "landed"])

    def test_append_rejects_invalid(self):
        root = Path(tempfile.mkdtemp())
        path = root / "journal.toml"
        with self.assertRaises(journal.JournalError):
            journal.append(path, [{"event": "gate", "work": "w-001", "at": "2026-09-11T03:15:00Z",
                                   "gate": "commit", "tree": "XYZ", "passed": "1", "total": "1", "attacks": "0"}])

    def test_utc_now_format(self):
        self.assertRegex(journal.utc_now(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


if __name__ == "__main__":
    unittest.main()
