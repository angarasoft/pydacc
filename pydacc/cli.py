"""pydacc CLI: gate, journal, map."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .access import map_
from .gate import Check, run
from .hash import content_hash
from .journal import parse, render

DEFAULT_JOURNAL = "journal"


def _root() -> Path:
    return Path.cwd()


def _cmd_hash(journal: str, rev: str) -> int:
    digest = content_hash(_root(), journal, rev)
    if digest is None:
        print(f"journal hash: revision {rev} cannot be read", file=sys.stderr)
        return 2
    print(digest)
    return 0


def _cmd_show(journal: str) -> int:
    path = Path(f"{journal}.toml")
    if not path.exists():
        print(f"journal show: {path} not found", file=sys.stderr)
        return 2
    for record in parse(path.read_text(encoding="utf-8")):
        print(render(record))
    return 0


def _cmd_map(fmt: str) -> int:
    print(map_(_root(), fmt))
    return 0


def _cmd_gate() -> int:
    checks = [
        Check("tests", ["python3", "-m", "unittest", "discover", "-s", "tests", "-t", "."]),
    ]
    verdict = run(_root(), checks)
    print(f"passed={verdict.passed_count} total={verdict.total}")
    if verdict.failed:
        print("failed: " + ", ".join(verdict.failed), file=sys.stderr)
    else:
        print("passed: " + ", ".join(verdict.passed))
    return 0 if verdict.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pydacc", description="DACC methodology for Python")
    parser.add_argument("--version", action="version", version=f"pydacc {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    journal_p = sub.add_parser("journal", help="append-only journal")
    journal_sub = journal_p.add_subparsers(dest="journal_command", required=True)
    hash_p = journal_sub.add_parser("hash", help="content hash of a tree without the journal")
    hash_p.add_argument("rev", nargs="?", default="HEAD")
    journal_sub.add_parser("show", help="print journal events")

    sub.add_parser("gate", help="run the check catalog")
    map_p = sub.add_parser("map", help="project map")
    map_p.add_argument("--format", choices=("text", "json"), default="text")

    args = parser.parse_args(argv)
    journal = DEFAULT_JOURNAL

    if args.command == "journal":
        if args.journal_command == "hash":
            return _cmd_hash(journal, args.rev)
        if args.journal_command == "show":
            return _cmd_show(journal)
    if args.command == "map":
        return _cmd_map(args.format)
    if args.command == "gate":
        return _cmd_gate()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
