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

## Not done yet (next slices)

- Runtime Odoo-registry introspection (the authoritative gate catalog).
- The compiled git-hook (Rust launcher) enforcing the invariants.
- `emit` (generated AGENTS.md / QWEN.md) and `where`/`refs` resolvers.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```
