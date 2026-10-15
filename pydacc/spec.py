"""Typed documentation content: RFC/plan/user-doc are code, not markdown.

The registry (``pydacc docs``) imports these modules and renders md/json/xml.
Content is typed data (dataclasses); forms are derived views of one source.

One decision kind — RFC. A module holds a contract ``__rfc__.py`` plus
numbered decisions ``rfc/NNNN.py``; business planning lives in ``plan/NNNN.py``
(same mechanics: statuses, supersedes, registry). Two status axes: document
lifecycle and implementation-in-code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(Enum):
    DRAFT = "draft"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"
    # SUPERSEDED is NOT written by the author: it is computed by the registry
    # when another document supersedes this one. Kept as an enum value for
    # rendering the effective status.
    SUPERSEDED = "superseded"


class Implementation(Enum):
    """Вторая ось: насколько решение реализовано в коде."""

    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    IMPLEMENTED = "implemented"
    OBSOLETE = "obsolete"


# Required sections for rfc/plan docs, validated by `pydacc docs check`
# (the formal RFC skeleton from the AngaraBase template, trimmed for Odoo
# addons). Инварианты and Открытые вопросы stay structured Doc fields.
RFC_SECTIONS: tuple[str, ...] = (
    "Резюме",
    "Мотивация",
    "Контракт",
    "Альтернативы",
    "Security",
    "Performance",
    "Verification",
    "Change Log",
)


@dataclass(frozen=True)
class Section:
    title: str
    body: str


@dataclass(frozen=True)
class Ref:
    module: str   # target module name, e.g. "payroll_core"
    kind: str     # "rfc" | "plan"
    ident: str    # decision number ("0001") or "" for the module contract


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


def _implementation(value: Implementation | str | None) -> Implementation | None:
    if value is None or isinstance(value, Implementation):
        return value
    try:
        return Implementation(value)
    except ValueError as exc:
        raise ValueError(
            f"unknown implementation {value!r}; use one of {[s.value for s in Implementation]}"
        ) from exc


PRIORITIES: tuple[str, ...] = ("P0", "P1", "P2")


@dataclass(frozen=True)
class Requirement:
    """Требование плана/RFC: не «добавить кнопку», а что, зачем и на что влияет.

    Каждое требование отвечает на четыре вопроса — без ответа на любой
    `pydacc docs check` его не примет:
    what — что делаем (данные, правило, функция, отчёт);
    why — зачем: основание (закон, форма, процесс) или бизнес-цель;
    affects — на что влияет: какие расчёты, проверки, данные меняются;
    used_in — где используется: формы, отчёты, процессы, модули-потребители.
    """

    ident: str
    what: str
    why: str
    affects: str
    used_in: tuple[str, ...]
    priority: str = "P1"
    target: str = ""                     # модуль, который реализует требование
    implementation: Implementation = Implementation.PLANNED
    refs: tuple[Ref, ...] = ()


def req(
    ident: str,
    what: str,
    *,
    why: str,
    affects: str,
    used_in: tuple[str, ...] | list[str],
    priority: str = "P1",
    target: str = "",
    implementation: Implementation | str = Implementation.PLANNED,
    refs: tuple[Ref, ...] = (),
) -> Requirement:
    return Requirement(
        ident=ident, what=what, why=why, affects=affects, used_in=tuple(used_in),
        priority=priority, target=target,
        implementation=_implementation(implementation) or Implementation.PLANNED,
        refs=tuple(refs),
    )


@dataclass(frozen=True)
class Doc:
    kind: str                 # "rfc" | "plan" | "user"
    module: str
    title: str
    status: Status
    summary: str = ""
    sections: tuple[Section, ...] = ()
    invariants: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    references: tuple[Ref, ...] = ()
    # Decisions this document replaces. The superseded document's status is
    # computed, never written there — a single source of truth for the graph.
    supersedes: tuple[Ref, ...] = ()
    ident: str = ""           # decision number; filled by the registry for rfc/NNNN.py and plan/NNNN.py
    implementation: Implementation | None = None
    requirements: tuple[Requirement, ...] = ()


def _decision(
    kind: str,
    module: str,
    title: str,
    status: Status | str,
    summary: str,
    sections: tuple[Section, ...],
    invariants: tuple[str, ...],
    open_questions: tuple[str, ...],
    references: tuple[Ref, ...],
    supersedes: tuple[Ref, ...],
    implementation: Implementation | str | None,
    requirements: tuple[Requirement, ...] = (),
) -> Doc:
    return Doc(
        kind=kind,
        module=module,
        title=title,
        status=_status(status),
        summary=summary,
        sections=tuple(sections),
        invariants=tuple(invariants),
        open_questions=tuple(open_questions),
        references=tuple(references),
        supersedes=tuple(supersedes),
        implementation=_implementation(implementation),
        requirements=tuple(requirements),
    )


def rfc(
    module: str,
    title: str,
    status: Status | str,
    summary: str = "",
    sections: tuple[Section, ...] = (),
    invariants: tuple[str, ...] = (),
    open_questions: tuple[str, ...] = (),
    references: tuple[Ref, ...] = (),
    supersedes: tuple[Ref, ...] = (),
    implementation: Implementation | str | None = None,
    requirements: tuple[Requirement, ...] | list[Requirement] = (),
) -> Doc:
    """RFC: модульный контракт (``__rfc__.py``) или решение (``rfc/NNNN.py``)."""
    return _decision(
        "rfc", module, title, status, summary, sections, invariants,
        open_questions, references, supersedes, implementation, tuple(requirements),
    )


def plan(
    module: str,
    title: str,
    status: Status | str,
    summary: str = "",
    sections: tuple[Section, ...] = (),
    invariants: tuple[str, ...] = (),
    open_questions: tuple[str, ...] = (),
    references: tuple[Ref, ...] = (),
    supersedes: tuple[Ref, ...] = (),
    implementation: Implementation | str | None = None,
    requirements: tuple[Requirement, ...] | list[Requirement] = (),
) -> Doc:
    """Plan: бизнес-планирование ДО решений (``plan/NNNN.py``), та же механика."""
    return _decision(
        "plan", module, title, status, summary, sections, invariants,
        open_questions, references, supersedes, implementation, tuple(requirements),
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
