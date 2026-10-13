"""Gate: run the check catalog and produce a structured verdict.

The catalog (which checks, thresholds) is configuration. The gate itself only
executes and counts; the immutable invariant — a landed event requires a gate
event with the same tree — is enforced by the journal, not here.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Check:
    name: str
    command: list[str]


@dataclass(frozen=True)
class Verdict:
    passed: list[str]
    failed: list[str]
    total: int

    @property
    def ok(self) -> bool:
        return not self.failed

    @property
    def passed_count(self) -> int:
        return len(self.passed)


def run(root: Path, checks: list[Check]) -> Verdict:
    passed: list[str] = []
    failed: list[str] = []
    for check in checks:
        result = subprocess.run(check.command, cwd=root, capture_output=True, text=True)
        if result.returncode == 0:
            passed.append(check.name)
        else:
            failed.append(check.name)
    return Verdict(passed=passed, failed=failed, total=len(checks))
