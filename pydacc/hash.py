"""Content hash of a git tree without the journal.

Faithful port of dacc's `proof::content_hash`: the proof is tied not to the
commit hash nor the raw tree hash, but to the SHA-1 (git blob) of the
NUL-separated `git ls-tree -r -z` listing with the journal directory and
`journal.toml` excluded.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(root: Path, args: list[str]) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=True
    ).stdout


def _git_stdin(root: Path, args: list[str], data: bytes) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], input=data, capture_output=True, check=True
    ).stdout.decode().strip()


def content_hash(root: Path, journal: str, tree: str) -> str | None:
    """SHA-1 (git blob) of `git ls-tree -r -z` of `tree`, minus the journal."""
    try:
        listing = _git(root, ["ls-tree", "-r", "-z", "--full-tree", tree])
    except subprocess.CalledProcessError:
        return None
    journal_dir = f"{journal}/".encode()
    journal_file = f"{journal}.toml".encode()
    kept = bytearray()
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        path = entry.split(b"\t", 1)[-1]
        if path.startswith(journal_dir) or path == journal_file:
            continue
        kept += entry + b"\0"
    try:
        return _git_stdin(root, ["hash-object", "--stdin"], bytes(kept))
    except subprocess.CalledProcessError:
        return None


def index_hash(root: Path, journal: str) -> str | None:
    """Hash of the tree being built (the git index), minus the journal."""
    try:
        tree = _git(root, ["write-tree"]).decode().strip()
    except subprocess.CalledProcessError:
        return None
    return content_hash(root, journal, tree)
