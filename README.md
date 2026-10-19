# pydacc

DACC methodology for Python: a gate, an append-only journal and an access layer
so that humans and agents share one interface and never re-introspect the tree.

This is the minimal core (first slice). It mirrors dacc's journal schema and
content-hash algorithm exactly, so a Python project is interchangeable with a
Rust one at the proof level.

## What works now

- `pydacc journal hash [rev]` — content hash of a tree without the journal
  (SHA-1 of the filtered `git ls-tree -r -z` listing).
- `pydacc journal show` — print journal events with strict validation.
- `pydacc map [--format json]` — static introspection of Python models.
- `pydacc gate` — run the check catalog and report a verdict.

## User stories (`pydacc docs`)

A module may carry user stories in `addons/<layer>/<module>/stories/NNNN.py`
(one `story(...)` per file, number = file name, ref: `ref(module, "story", "NNNN")`):

```python
from pydacc.spec import ref, scenario, step, story

STORY = story(
    module="hrm_core", title="Приём на работу",
    role="кадровик", goal="оформить приём", benefit="работник появился в штате",
    implements=(ref("hrm_core", "plan", "0001"),), requirements=("HRM-EFF-01",),
    steps=("Открыть «Сотрудники»", step("Открыть карточку", "static/description/stories/hire_1.png")),
    scenarios=(scenario("S1", "работник без назначения", "кадровик принимает",
                        "создано назначение", tests=("hrm_core.tests.test_hire.TestHire.test_hire",)),),
)
```

A story in a dependent module extends it (superposition): `extends=ref(...)`,
new `scenarios`, `replaces={"S1": scenario("S1", ...)}`,
`steps_after={"Открыть карточку": ["Заполнить СНИЛС"]}`, trailing `steps`.

- `pydacc docs check` — shape, unique scenario idents, `extends` only into the
  transitive `depends` (base never extends country, no cycles), `replaces` /
  `steps_after` against the composed base, `implements` / `requirements`
  against rfc/plan docs, test ids resolve to file/class/method, screenshots exist.
- `pydacc docs render --solution <module> [--format json]` — user guide of a
  solution: stories of its `depends` closure with extensions applied in
  dependency order. `docs list|status|render --module` include stories.

### Guide fields (all optional)

```python
STORY = story(
    module="hrm_core", title="Приём работника", role="кадровик", goal="…", benefit="…",
    section="Работники", order=10,                     # guide chapter / place in it
    menus=("hrm_core.menu_hrm_employees_list",),       # menu items the story belongs to
    notes="Приём — только с даты.",                     # user-facing «Важно»
    dev_notes="Мастер — hrm.employee.wizard.",         # developer guide only
    scenarios=(scenario("S1", "…", "…", "…", title="Приём с будущей даты"),),
)
```

- `section` / `order` (default 100) — base story only; an extension inherits them.
- `menus` — fully qualified xml ids `<module>.<menu id>`; an extension may add
  menus (merged after the base ones). `docs check`: menus need a `section`
  (in the base story); the module part must be the story module or in its
  `depends` closure; the id must be a `<menuitem id>` (nested ones too) or a
  `<record model="ir.ui.menu" id>` in that module's `*.xml` (id with or without
  the module prefix).
- `notes` / `dev_notes` — extensions append theirs.
- `scenario(..., title=…)` — short caption shown in the user guide instead of the ident.

### Audiences

`pydacc docs render --solution M [--audience dev|user] [--format md|json]`
(`--audience` only with `--solution`; default `dev`).

- `dev` — stories in module dependency order with scenarios (Дано/Когда/Тогда,
  tests), modules, section, menus, technical notes.
- `user` — end-user guide: `# Руководство пользователя`, a `##` chapter per
  section (sections by the minimal `order` of their stories, then name;
  stories without a section in the last chapter «Прочее»), a `###` story per
  story (by `order`, then title): «Роль: цель, чтобы польза.», `#### Как сделать`
  (numbered steps, screenshots), `#### Как это работает` (one rule per scenario:
  «**Заголовок.** Если <дано> и <когда>, то <тогда>.»), `> **Важно.** <notes>`.
  No tests, refs, modules or `dev_notes`.

### Guide JSON (for an in-app help center)

`--format json` prints one object; `format` is bumped on incompatible changes.

```text
{
  "format": 1, "audience": "user" | "dev", "solution": "<module>",
  "stories": [{
    "key": "<module>::story/NNNN",        # stable id: base story module + number
    "section": str,                       # "" = no section (md: «Прочее»)
    "order": int,
    "title": str, "role": str, "goal": str, "benefit": str,
    "menus": [str],                       # "<module>.<menu xml id>", base then extensions
    "steps": [{"text": str, "screenshot": str}],   # screenshot: path from the project
                                                   # root ("" = none); for Odoo the URL is
                                                   # /<module>/<path inside the module>
    "scenarios": [{"ident": str, "title": str, "given": str, "when": str, "then": str}],
    "notes": [str],                       # base first, then extensions
    "modules": [str]                      # base module, then extensions applied
  }]
}
```

`user` stories come in guide order (chapters, then order within them). `dev`
stories come in module dependency order and additionally carry `module`,
`ident`, `implements` (`[{module, kind, ident}]`), `requirements`, `dev_notes`
(`[str]`) and `tests` in every scenario.

## Not done yet (next slices)

- Runtime Odoo-registry introspection (the authoritative gate catalog).
- The compiled git-hook (Rust launcher) enforcing the invariants.
- `emit` (generated AGENTS.md / QWEN.md) and `where`/`refs` resolvers.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```
