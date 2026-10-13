import subprocess
import tempfile
import unittest
from pathlib import Path

from pydacc.hash import content_hash


class HashTest(unittest.TestCase):
    def _repo(self) -> Path:
        root = Path(tempfile.mkdtemp())
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
        return root

    def _commit(self, root: Path, name: str, content: str) -> None:
        (root / name).write_text(content)
        subprocess.run(["git", "-C", str(root), "add", name], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", name], check=True)

    def test_returns_40_hex(self):
        root = self._repo()
        self._commit(root, "a.txt", "hello")
        digest = content_hash(root, "journal", "HEAD")
        self.assertIsNotNone(digest)
        self.assertEqual(len(digest), 40)
        self.assertTrue(all(c in "0123456789abcdef" for c in digest))

    def test_excludes_journal(self):
        root = self._repo()
        self._commit(root, "a.txt", "hello")
        without = content_hash(root, "journal", "HEAD")
        (root / "journal.toml").write_text("[[events]]\n")
        subprocess.run(["git", "-C", str(root), "add", "journal.toml"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "journal"], check=True)
        self.assertEqual(content_hash(root, "journal", "HEAD"), without)


if __name__ == "__main__":
    unittest.main()
