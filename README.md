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

## Not done yet (next slices)

- Runtime Odoo-registry introspection (the authoritative gate catalog).
- The compiled git-hook (Rust launcher) enforcing the invariants.
- `emit` (generated AGENTS.md / QWEN.md) and `where`/`refs` resolvers.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```
