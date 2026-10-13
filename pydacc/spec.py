"""Typed documentation content: RFC/ADR/user-doc are code, not markdown.

The registry (``pydacc docs``) imports these modules and renders md/json/xml.
Content is typed data (dataclasses); forms are derived views of one source.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(Enum):
    DRAFT = "draft"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class Section:
    title: str
    body: str


@dataclass(frozen=True)
class Ref:
    module: str   # target module name, e.g. "payroll_core"
    kind: str     # "rfc" | "adr"
    ident: str    # adr number ("0001") or "" for rfc


def ref(module: str, kind: str, ident: str = "") -> Ref:
    return Ref(module=module, kind=kind, ident=ident)


def _status(value: Status | str) -> Status:
    if isinstance(value, Status):
        return value
    try:
        return Status(value)
    except ValueError as exc:
        raise ValueError(
            f"unknown status {value!r}; use one of {[s.value for s in Status]}"
        ) from exc


@dataclass(frozen=True)
class Doc:
    kind: str                 # "rfc" | "adr" | "user"
    module: str
    title: str
    status: Status
    summary: str = ""
    sections: tuple[Section, ...] = ()
    invariants: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    references: tuple[Ref, ...] = ()
    ident: str = ""           # adr number; filled by the registry for adr docs


def rfc(
    module: str,
    title: str,
    status: Status | str,
    summary: str = "",
    sections: tuple[Section, ...] = (),
    invariants: tuple[str, ...] = (),
    open_questions: tuple[str, ...] = (),
    references: tuple[Ref, ...] = (),
) -> Doc:
    return Doc(
        kind="rfc",
        module=module,
        title=title,
        status=_status(status),
        summary=summary,
        sections=tuple(sections),
        invariants=tuple(invariants),
        open_questions=tuple(open_questions),
        references=tuple(references),
    )


def adr(
    module: str,
    title: str,
    status: Status | str,
    ident: str = "",
    summary: str = "",
    sections: tuple[Section, ...] = (),
    references: tuple[Ref, ...] = (),
) -> Doc:
    # ident comes from the file name (__adr__/0001.py) — the registry fills it,
    # so it must NOT be duplicated in the content (single source, no drift).
    return Doc(
        kind="adr",
        module=module,
        ident=ident,
        title=title,
        status=_status(status),
        summary=summary,
        sections=tuple(sections),
        references=tuple(references),
    )


def user_doc(
    module: str,
    title: str,
    summary: str = "",
    sections: tuple[Section, ...] = (),
) -> Doc:
    return Doc(
        kind="user",
        module=module,
        title=title,
        status=Status.ACCEPTED,
        summary=summary,
        sections=tuple(sections),
    )
