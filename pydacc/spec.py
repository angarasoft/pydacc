"""Typed documentation content: RFC/plan/user-doc/story are code, not markdown.

The registry (``pydacc docs``) imports these modules and renders md/json/xml.
Content is typed data (dataclasses); forms are derived views of one source.

One decision kind — RFC. A module holds a contract ``__rfc__.py`` plus
numbered decisions ``rfc/NNNN.py``; business planning lives in ``plan/NNNN.py``
(same mechanics: statuses, supersedes, registry). Two status axes: document
lifecycle and implementation-in-code.

User stories live in ``stories/NNNN.py`` (:class:`Story`): «как <роль> я хочу
<цель>, чтобы <польза>» plus scenarios bound to tests and illustrated steps. A
story in a dependent module may extend a story of its dependency (superposition):
add scenarios, replace them, insert steps; the registry composes the user guide
of a solution from the stories of the modules it installs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    kind: str     # "rfc" | "plan" | "story"
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


@dataclass(frozen=True)
class Scenario:
    """Сценарий истории: Дано / Когда / Тогда, подтверждённый тестами.

    tests — dotted ids ``<module>.tests.<test_file>[.<Class>[.<method>]]``;
    `pydacc docs check` resolves each to a file, class and method.
    title — short user-facing caption («Приём с будущей даты»); the user
    guide shows it instead of the ident.
    """

    ident: str                      # "S1"; unique within the composed story
    given: str
    when: str
    then: str
    tests: tuple[str, ...] = ()
    title: str = ""


def scenario(
    ident: str,
    given: str,
    when: str,
    then: str,
    tests: tuple[str, ...] | list[str] = (),
    title: str = "",
) -> Scenario:
    return Scenario(ident=ident, given=given, when=when, then=then, tests=tuple(tests), title=title)


@dataclass(frozen=True)
class Step:
    """Шаг пользователя; screenshot — путь относительно каталога модуля."""

    text: str
    screenshot: str = ""


def step(text: str, screenshot: str = "") -> Step:
    return Step(text=text, screenshot=screenshot)


StepLike = Step | str


def _steps(items: tuple[StepLike, ...] | list[StepLike]) -> tuple[Step, ...]:
    """Plain strings are steps without a screenshot."""
    out: list[Step] = []
    for item in items:
        if isinstance(item, Step):
            out.append(item)
        elif isinstance(item, str):
            out.append(Step(text=item))
        else:
            raise TypeError(f"step must be str or Step, got {type(item).__name__}")
    return tuple(out)


DEFAULT_STORY_ORDER = 100


@dataclass(frozen=True)
class Story:
    """Пользовательская история модуля (``stories/NNNN.py``).

    Base story (``extends is None``): «Как <role> я хочу <goal>, чтобы <benefit>»,
    scenarios and steps. Extension (``extends`` = ref to a story of a dependency):
    ``scenarios`` are added, ``replaces`` swaps base scenarios by ident,
    ``steps_after`` inserts steps after a base step (exact text), ``steps`` are
    appended. role/goal/benefit always come from the base story.

    Guide placement (base story only; an extension inherits it): ``section`` is
    the guide chapter, ``order`` the place within it. ``menus`` are fully
    qualified xml ids of the menu items the story belongs to (in-app help shows
    it to users who see one of them); an extension may add menus. ``notes`` is
    the user-facing «Важно» note, ``dev_notes`` technical details rendered only
    for developers; extensions append both.
    """

    module: str
    title: str
    role: str = ""
    goal: str = ""
    benefit: str = ""
    implements: tuple[Ref, ...] = ()        # rfc/plan docs this story realises
    requirements: tuple[str, ...] = ()      # requirement idents from those docs
    scenarios: tuple[Scenario, ...] = ()
    steps: tuple[Step, ...] = ()
    extends: Ref | None = None
    replaces: dict[str, Scenario] = field(default_factory=dict, hash=False)
    steps_after: dict[str, tuple[Step, ...]] = field(default_factory=dict, hash=False)
    notes: str = ""
    section: str = ""                       # guide chapter («Работники»); base only
    order: int = DEFAULT_STORY_ORDER        # place within the section; base only
    menus: tuple[str, ...] = ()             # "<module>.<menu xml id>"
    dev_notes: str = ""                     # technical details, developer guide only
    ident: str = ""                         # filled by the registry from the file name
    kind: str = "story"


def story(
    module: str,
    title: str,
    role: str = "",
    goal: str = "",
    benefit: str = "",
    implements: tuple[Ref, ...] | list[Ref] = (),
    requirements: tuple[str, ...] | list[str] = (),
    scenarios: tuple[Scenario, ...] | list[Scenario] = (),
    steps: tuple[StepLike, ...] | list[StepLike] = (),
    extends: Ref | None = None,
    replaces: dict[str, Scenario] | None = None,
    steps_after: dict[str, tuple[StepLike, ...] | list[StepLike]] | None = None,
    notes: str = "",
    section: str = "",
    order: int = DEFAULT_STORY_ORDER,
    menus: tuple[str, ...] | list[str] = (),
    dev_notes: str = "",
) -> Story:
    """User story (``stories/NNNN.py``); an extension sets ``extends``."""
    if extends is not None and not isinstance(extends, Ref):
        raise TypeError("extends must be ref(module, 'story', 'NNNN')")
    if isinstance(menus, str):
        raise TypeError("menus must be a tuple of xml ids, e.g. ('hrm_core.menu_x',)")
    if isinstance(order, bool) or not isinstance(order, int):
        raise TypeError("order must be an int")
    return Story(
        module=module,
        title=title,
        role=role,
        goal=goal,
        benefit=benefit,
        implements=tuple(implements),
        requirements=tuple(requirements),
        scenarios=tuple(scenarios),
        steps=_steps(steps),
        extends=extends,
        replaces=dict(replaces or {}),
        steps_after={
            anchor: _steps((v,) if isinstance(v, (str, Step)) else v)
            for anchor, v in (steps_after or {}).items()
        },
        notes=notes,
        section=section,
        order=order,
        menus=tuple(menus),
        dev_notes=dev_notes,
    )
