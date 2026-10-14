"""Gate: run the check catalog and produce a structured verdict.

The catalog (which checks, thresholds) is configuration. The gate itself only
executes and counts; the immutable invariant — a landed event requires a gate
event with the same tree — is enforced by the journal, not here.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
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
    # Output of failed checks: the agent learns the rule from the error.
    output: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed

    @property
    def passed_count(self) -> int:
        return len(self.passed)


def run(
    root: Path,
    checks: list[Check],
    env: Mapping[str, str] | None = None,
    on_start: Callable[[str], None] | None = None,
) -> Verdict:
    """Run checks in order. `env` is added to the environment of every check
    (e.g. PYDACC_WORK / PYDACC_COMMIT_MESSAGE during `commit`)."""
    full_env = {**os.environ, **(env or {})}
    passed: list[str] = []
    failed: list[str] = []
    output: dict[str, str] = {}
    for check in checks:
        if on_start is not None:
            on_start(check.name)
        result = subprocess.run(
            check.command, cwd=root, capture_output=True, text=True, env=full_env
        )
        if result.returncode == 0:
            passed.append(check.name)
        else:
            failed.append(check.name)
            output[check.name] = "\n".join(
                part.strip() for part in (result.stdout, result.stderr) if part.strip()
            )
    return Verdict(passed=passed, failed=failed, total=len(checks), output=output)
