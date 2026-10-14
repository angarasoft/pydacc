"""pydacc CLI: gate, journal, map."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import subprocess

from . import __version__
from .access import emit_docs, map_, refs_, where_
from .config import load_checks
from .deadfields import report as deadfields_report
from .docs import (
    discover,
    effective_status,
    freshness,
    graph_report,
    loaded_docs,
    render_json,
    render_md,
    status_report,
    validate,
    warnings,
)
from .gate import Check, run
from .hash import content_hash, index_hash
from .journal import SELF_COMMIT, append, parse, render, utc_now

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


def _checks() -> list[Check]:
    configured = load_checks(_root())
    if configured is not None:
        return configured
    return [
        Check("tests", ["python3", "-m", "unittest", "discover", "-s", "tests", "-t", "."]),
        Check("cargo-test", ["cargo", "test", "--manifest-path", "crates/pydacc-gate/Cargo.toml", "--quiet"]),
        Check("emit-fresh", ["python3", "-m", "pydacc.cli", "emit", "--check"]),
    ]


def _cmd_gate() -> int:
    verdict = run(_root(), _checks())
    print(f"passed={verdict.passed_count} total={verdict.total}")
    if verdict.failed:
        print("failed: " + ", ".join(verdict.failed), file=sys.stderr)
    else:
        print("passed: " + ", ".join(verdict.passed))
    return 0 if verdict.ok else 1


def _cmd_commit(journal: str, work: str, message: str) -> int:
    staged = subprocess.run(
        ["git", "-C", str(_root()), "diff", "--cached", "--quiet"]
    ).returncode != 0
    if not staged:
        print("commit: nothing staged — stage your work first (git add)", file=sys.stderr)
        return 2
    verdict = run(_root(), _checks())
    if not verdict.ok:
        print("gate failed: " + ", ".join(verdict.failed), file=sys.stderr)
        return 1
    tree = index_hash(_root(), journal)
    if tree is None:
        print("commit: cannot hash the index (nothing staged?)", file=sys.stderr)
        return 2
    at = utc_now()
    events = [
        {
            "event": "gate", "work": work, "at": at, "gate": "commit", "tree": tree,
            "passed": str(verdict.passed_count), "total": str(verdict.total), "attacks": "0",
        },
        {"event": "landed", "work": work, "at": at, "commit": SELF_COMMIT, "tree": tree},
    ]
    append(Path(f"{journal}.toml"), events)
    subprocess.run(["git", "-C", str(_root()), "add", f"{journal}.toml"], check=True)
    subprocess.run(["git", "-C", str(_root()), "commit", "-m", message], check=True)
    print(f"landed {work} tree={tree}")
    return 0


def _cmd_emit(check: bool) -> int:
    docs = emit_docs(_root())
    if check:
        drifted = [
            name
            for name, content in docs.items()
            if not Path(name).exists() or Path(name).read_text(encoding="utf-8") != content
        ]
        if drifted:
            print("emit --check: drifted: " + ", ".join(drifted), file=sys.stderr)
            return 1
        print("emit --check: fresh")
        return 0
    for name, content in docs.items():
        Path(name).write_text(content, encoding="utf-8")
        print(f"emit: {name} written")
    return 0


def _cmd_where(file: str) -> int:
    print(where_(_root(), file))
    return 0


def _cmd_refs(term: str) -> int:
    print(refs_(_root(), term))
    return 0


def _cmd_deadfields() -> int:
    print(deadfields_report(_root()))
    return 0


def _cmd_docs_list() -> int:
    for loc in discover(_root()):
        print(f"{loc.rel}\t{loc.kind}\t{loc.layer}\t{loc.module}")
    return 0


def _cmd_docs_validate() -> int:
    problems = validate(_root())
    for p in problems:
        print(p, file=sys.stderr)
    print(f"docs validate: {'ok' if not problems else f'{len(problems)} problem(s)'}")
    return 0 if not problems else 1


def _cmd_docs_check() -> int:
    """Validate refs/schema/supersedes graph and user.md freshness (for gate)."""
    problems = validate(_root()) + freshness(_root())
    soft = warnings(_root())
    for p in problems:
        print(p, file=sys.stderr)
    for w in soft:
        print(f"warning: {w}", file=sys.stderr)
    print(f"docs check: {'fresh' if not problems else f'{len(problems)} problem(s)'}")
    return 0 if not problems else 1


def _cmd_docs_status() -> int:
    print(status_report(_root()))
    return 0


def _cmd_docs_graph(module: str | None) -> int:
    print(graph_report(_root(), module))
    return 0


def _cmd_docs_render(module: str | None, fmt: str) -> int:
    docs, sb, _ = loaded_docs(_root())
    keys = sorted(docs)
    if module is not None:
        keys = [k for k in keys if k[0] == module]
    if not keys:
        print("docs render: no docs found", file=sys.stderr)
        return 2
    for key in keys:
        loc, doc = docs[key]
        eff = effective_status(doc, key in sb)
        print(f"# {loc.rel}", file=sys.stderr)
        print(render_json(loc, doc, eff) if fmt == "json" else render_md(loc, doc, eff))
    return 0


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
    commit_p = sub.add_parser("commit", help="gate → journal → commit in one command")
    commit_p.add_argument("--work", required=True, help="work slug like w-fix-x")
    commit_p.add_argument("-m", "--message", required=True, help="commit message")
    map_p = sub.add_parser("map", help="project map")
    map_p.add_argument("--format", choices=("text", "json"), default="text")
    emit_p = sub.add_parser("emit", help="generate AGENTS.md + QWEN.md from introspection")
    emit_p.add_argument("--check", action="store_true", help="fail if the generated files drifted")
    where_p = sub.add_parser("where", help="what is known about a file")
    where_p.add_argument("--file", required=True)
    refs_p = sub.add_parser("refs", help="where a term appears")
    refs_p.add_argument("term")
    sub.add_parser("deadfields", help="dead-field candidates (defined but never referenced)")

    docs_p = sub.add_parser("docs", help="manage RFC/plan/user docs as code")
    docs_sub = docs_p.add_subparsers(dest="docs_command", required=True)
    docs_sub.add_parser("list", help="list discovered doc modules")
    docs_sub.add_parser("validate", help="check schema + refs + supersedes graph")
    docs_sub.add_parser("check", help="validate + committed user.md freshness (for gate)")
    docs_sub.add_parser("status", help="declared vs effective status of all decisions")
    graph_p = docs_sub.add_parser("graph", help="supersedes chain (было → стало)")
    graph_p.add_argument("--module", help="only this module")
    render_p = docs_sub.add_parser("render", help="render docs to md/json")
    render_p.add_argument("--module", help="render only this module")
    render_p.add_argument("--format", choices=("md", "json"), default="md")

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
    if args.command == "commit":
        return _cmd_commit(journal, args.work, args.message)
    if args.command == "emit":
        return _cmd_emit(args.check)
    if args.command == "where":
        return _cmd_where(args.file)
    if args.command == "refs":
        return _cmd_refs(args.term)
    if args.command == "deadfields":
        return _cmd_deadfields()
    if args.command == "docs":
        if args.docs_command == "list":
            return _cmd_docs_list()
        if args.docs_command == "validate":
            return _cmd_docs_validate()
        if args.docs_command == "check":
            return _cmd_docs_check()
        if args.docs_command == "status":
            return _cmd_docs_status()
        if args.docs_command == "graph":
            return _cmd_docs_graph(args.module)
        if args.docs_command == "render":
            return _cmd_docs_render(args.module, args.format)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
