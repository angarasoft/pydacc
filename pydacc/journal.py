"""Append-only journal, mirroring dacc's event schema and strict flat-TOML format.

Format: `key = "string"` pairs, one `[[events]]` table per event; blank lines
and `# …` comments are allowed, nothing else. Field rules follow dacc exactly:
40/64-hex hashes, UTC timestamps, integer counts, `commit = "self"` only with
gate evidence, and the anti-vacuum proof fields.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

SELF_COMMIT = "self"

KINDS = ("started", "gate", "landed", "abandoned", "closed", "void")
_PROOFS = ("red_before", "mutation_proof", "anti_vacuum")

_HASH = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_SUBJECT = re.compile(r"^[ws]-.+$")


class JournalError(Exception):
    def __init__(self, line: int, reason: str):
        super().__init__(f"{reason} (line {line})")
        self.line = line
        self.reason = reason


def parse(text: str) -> list[dict[str, str]]:
    """Parse journal text into validated, ordered event records."""
    records: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for i, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        n = i + 1
        if line == "[[events]]":
            if current is not None:
                records.append(current)
            current = {}
            continue
        if current is None:
            raise JournalError(n, "expected `[[events]]` before the first event")
        key, value = _pair(line, n)
        if key in current:
            raise JournalError(n, f"key `{key}` is repeated")
        current[key] = value
    if current is not None:
        records.append(current)
    if not records:
        raise JournalError(1, "the journal has no events")
    for record in records:
        _validate(record)
    return records


def render(record: dict[str, str]) -> str:
    lines = ["[[events]]"]
    lines.extend(f'{key} = "{_escape(value)}"' for key, value in record.items())
    return "\n".join(lines) + "\n"


def _pair(line: str, n: int) -> tuple[str, str]:
    if "=" not in line:
        raise JournalError(n, 'expected `key = "string"`')
    key, _, value = line.partition("=")
    key = key.strip()
    if not _KEY.match(key):
        raise JournalError(
            n,
            f"key `{key}` is lowercase latin letters, digits and `_`, starting with a letter",
        )
    return key, _string(value.strip(), n)


def _string(value: str, n: int) -> str:
    if len(value) < 2 or not value.startswith('"') or not value.endswith('"'):
        raise JournalError(n, "a value is a double-quoted string and nothing else on the line")
    inner = value[1:-1]
    out: list[str] = []
    chars = iter(inner)
    for c in chars:
        if c == "\\":
            esc = next(chars, "")
            if esc == '"':
                out.append('"')
            elif esc == "\\":
                out.append("\\")
            elif esc == "n":
                out.append("\n")
            elif esc == "t":
                out.append("\t")
            else:
                raise JournalError(n, 'a string allows only the escapes \\" \\\\ \\n \\t')
        elif c == '"':
            raise JournalError(n, "an unescaped quote inside a string")
        elif ord(c) < 0x20 and c not in "\n\t":
            raise JournalError(n, "a control character in a string")
        else:
            out.append(c)
    return "".join(out)


def _escape(value: str) -> str:
    out: list[str] = []
    for c in value:
        if c == '"':
            out.append('\\"')
        elif c == "\\":
            out.append("\\\\")
        elif c == "\n":
            out.append("\\n")
        elif c == "\t":
            out.append("\\t")
        elif ord(c) < 0x20:
            out.append(" ")
        else:
            out.append(c)
    return "".join(out)


def _validate(record: dict[str, str]) -> None:
    name = record.get("event")
    if name not in KINDS:
        raise JournalError(0, f"unknown event `{name}`: {', '.join(KINDS)}")

    if name == "void":
        subject_key = "slice" if "slice" in record else "work"
        own: tuple[str, ...] = ("voids", "reason")
    elif name == "closed":
        subject_key = "slice"
        own = ()
    elif name == "gate":
        subject_key = "work"
        own = ("gate", "tree", "verdict", "passed", "total", "skipped", "attacks", "msrv", "executor")
    elif name == "landed":
        subject_key = "work"
        own = ("commit", "tree", "evidence", "red_before", "mutation_proof", "anti_vacuum", "executor")
    elif name == "abandoned":
        subject_key = "work"
        own = ("reason",)
    else:  # started
        subject_key = "work"
        own = ()

    for key in record:
        if key in ("event", "at", subject_key):
            continue
        if key not in own:
            raise JournalError(0, f"extra field `{key}` on a {name} event")

    subject = record.get(subject_key)
    if subject is None or not _SUBJECT.match(subject):
        raise JournalError(0, f"field {subject_key} is an identifier like {subject_key[0]}-…, not {subject!r}")

    at = record.get("at")
    if at is None or not _TS.match(at):
        raise JournalError(0, f"field at is a UTC time like 2026-09-11T03:15:00Z, not {at!r}")

    def required(key: str) -> str:
        value = record.get(key)
        if value is None or not value.strip():
            raise JournalError(0, f"no non-empty field {key} on a {name} event")
        return value

    def hash_field(key: str) -> str:
        value = required(key)
        if not _HASH.match(value):
            raise JournalError(0, f"field {key} is a git hash of 40 or 64 lowercase hexadecimal characters")
        return value

    def number(key: str) -> int:
        value = required(key)
        if not value.isdigit():
            raise JournalError(0, f"field {key} is a non-negative number, not {value!r}")
        return int(value)

    if name == "gate":
        required("gate")
        hash_field("tree")
        if "verdict" in record:
            return  # prose verdict: structured fields are not required
        number("passed")
        number("total")
        if "skipped" in record:
            required("skipped")
        number("attacks")
        if "msrv" in record:
            required("msrv")
    elif name == "landed":
        evidence = record.get("evidence")
        if evidence is not None and evidence != "history":
            raise JournalError(0, f"field evidence is only history, not {evidence!r}")
        for proof in _PROOFS:
            if proof in record:
                required(proof)
        if record.get("commit") == SELF_COMMIT:
            if evidence is not None:
                raise JournalError(0, "field commit is self only with the gate evidence")
        else:
            hash_field("commit")
        hash_field("tree")
    elif name == "abandoned":
        required("reason")
    elif name == "void":
        required("voids")
        required("reason")


def utc_now() -> str:
    """Current UTC time as a journal timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append(path: Path, events: list[dict[str, str]]) -> None:
    """Validate and append events to a journal file."""
    for event in events:
        parse(render(event))  # validates before anything is written
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + "".join(render(event) for event in events), encoding="utf-8")
