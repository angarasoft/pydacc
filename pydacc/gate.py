"""Gate: run the check catalog and produce a structured verdict.

The catalog (which checks, thresholds) is configuration. The gate itself only
executes and counts; the immutable invariant — a landed event requires a gate
event with the same tree — is enforced by the journal, not here.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Check:
    name: str
    command: list[str]
    # Run on the index snapshot (what is being committed), not the working tree.
    snapshot: bool = False


@dataclass(frozen=True)
class Verdict:
    passed: list[str]
    failed: list[str]
    total: int
    # Output of failed checks: the agent learns the rule from the error.
    output: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed

    @property
    def passed_count(self) -> int:
        return len(self.passed)


def has_staged(root: Path) -> bool:
    return subprocess.run(["git", "-C", str(root), "diff", "--cached", "--quiet"]).returncode != 0


@contextmanager
def index_snapshot(root: Path, links: Sequence[str] = ()) -> Iterator[Path]:
    """The index exported to a temporary directory: what a commit will contain,
    without unstaged edits and untracked files. `links` — untracked paths a check
    needs (virtualenv, local secrets, build output) — are symlinked from `root`."""
    dest = Path(tempfile.mkdtemp(prefix="pydacc-snapshot-"))
    try:
        subprocess.run(
            ["git", "-C", str(root), "checkout-index", "--all", f"--prefix={dest}/"],
            check=True, capture_output=True,
        )
        for rel in links:
            src, dst = root / rel, dest / rel
            if src.exists() and not dst.exists() and not dst.is_symlink():
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.symlink_to(src.resolve())
        yield dest
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def run(
    root: Path,
    checks: list[Check],
    env: Mapping[str, str] | None = None,
    on_start: Callable[[str], None] | None = None,
    snapshot: Path | None = None,
) -> Verdict:
    """Run checks in order. `env` is added to the environment of every check
    (e.g. PYDACC_WORK / PYDACC_COMMIT_MESSAGE during `commit`). Checks marked
    `snapshot` run in `snapshot` (see index_snapshot) when it is given, else in
    `root`; PYDACC_ROOT always points at the repository."""
    full_env = {**os.environ, **(env or {}), "PYDACC_ROOT": str(root)}
    passed: list[str] = []
    failed: list[str] = []
    output: dict[str, str] = {}
    for check in checks:
        if on_start is not None:
            on_start(check.name)
        cwd = snapshot if check.snapshot and snapshot is not None else root
        result = subprocess.run(
            check.command, cwd=cwd, capture_output=True, text=True, env=full_env
        )
        if result.returncode == 0:
            passed.append(check.name)
        else:
            failed.append(check.name)
            output[check.name] = "\n".join(
                part.strip() for part in (result.stdout, result.stderr) if part.strip()
            )
    return Verdict(passed=passed, failed=failed, total=len(checks), output=output)
