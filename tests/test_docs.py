import json
import tempfile
import unittest
from pathlib import Path

from pydacc.docs import (
    discover,
    freshness,
    graph_report,
    load,
    loaded_docs,
    render_json,
    render_md,
    status_report,
    validate,
    warnings,
)
from pydacc.spec import RFC_SECTIONS, Status

SECTIONS_PY = "sections=(" + ", ".join(f'Section("{t}", "body")' for t in RFC_SECTIONS) + ")"


def _write_module(root: Path, module: str, layer: str = "base") -> Path:
    mod = root / "addons" / layer / module
    mod.mkdir(parents=True)
    return mod


def _sample_rfc(mod: Path, status: str = "DRAFT") -> None:
    (mod / "__rfc__.py").write_text(
        "from pydacc.spec import rfc, Section, Status, ref\n"
        f'RFC = rfc(module="{mod.name}", title="Payroll Engine", status=Status.{status},'
        f' summary="s", {SECTIONS_PY}, invariants=("i1",),'
        ' implementation="implemented",'
        f' references=(ref("payroll_core", "rfc", "0001"),))\n'
    )


def _sample_decision(mod: Path, ident: str, supersedes: str = "") -> None:
    dec_dir = mod / "rfc"
    dec_dir.mkdir(exist_ok=True)
    body = (
        "from pydacc.spec import rfc, Section, Status, ref\n"
        f'RFC = rfc(module="{mod.name}", title="Pick mechanism", status=Status.ACCEPTED,'
        f' summary="why", {SECTIONS_PY}'
    )
    if supersedes:
        body += f', supersedes=(ref("{mod.name}", "rfc", "{supersedes}"),)'
    body += ")\n"
    (dec_dir / f"{ident}.py").write_text(body)


def _sample_plan(mod: Path, ident: str) -> None:
    plan_dir = mod / "plan"
    plan_dir.mkdir(exist_ok=True)
    (plan_dir / f"{ident}.py").write_text(
        "from pydacc.spec import plan, Section, Status\n"
        f'PLAN = plan(module="{mod.name}", title="Business reqs", status=Status.DRAFT,'
        f' summary="why", {SECTIONS_PY})\n'
    )


def _sample_user(mod: Path) -> None:
    d = mod / "docs"
    d.mkdir()
    (d / "user.py").write_text(
        "from pydacc.spec import user_doc, Section\n"
        f'DOC = user_doc(module="{mod.name}", title="How to use",'
        ' sections=(Section("Step 1", "do this"),))\n'
    )


def _eff(root: Path, kind: str, ident: str = "") -> Status:
    docs, sb, _ = loaded_docs(root)
    key = ("payroll_core", kind, ident)
    return Status.SUPERSEDED if key in sb else docs[key][1].status


class DiscoverTest(unittest.TestCase):
    def test_finds_all_kinds(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_rfc(mod)
        _sample_decision(mod, "0001")
        _sample_plan(mod, "0001")
        _sample_user(mod)
        located = discover(root)
        kinds = {l.kind for l in located}
        self.assertEqual(kinds, {"rfc", "plan", "user"})

    def test_decision_ident_from_path(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_decision(mod, "0042")
        located = [l for l in discover(root) if l.kind == "rfc" and l.ident]
        self.assertEqual(len(located), 1)
        self.assertEqual(located[0].ident, "0042")

    def test_no_addons(self):
        root = Path(tempfile.mkdtemp())
        self.assertEqual(discover(root), [])


class LoadTest(unittest.TestCase):
    def test_load_rfc_contract(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_rfc(mod)
        loc = next(l for l in discover(root) if l.kind == "rfc" and not l.ident)
        doc = load(root, loc)
        self.assertEqual(doc.title, "Payroll Engine")
        self.assertEqual(doc.module, "payroll_core")
        self.assertEqual(doc.ident, "")

    def test_decision_ident_from_filename(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_decision(mod, "0042")
        loc = next(l for l in discover(root) if l.ident == "0042")
        self.assertEqual(load(root, loc).ident, "0042")


class RenderTest(unittest.TestCase):
    def test_render_md(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_rfc(mod)
        docs, sb, _ = loaded_docs(root)
        key = ("payroll_core", "rfc", "")
        loc, doc = docs[key]
        eff = Status.SUPERSEDED if key in sb else doc.status
        out = render_md(loc, doc, eff)
        self.assertIn("# Payroll Engine", out)
        self.assertIn("- **Реализация:** implemented", out)
        self.assertIn("## Инварианты", out)
        self.assertIn("`payroll_core::rfc/0001`", out)

    def test_render_json(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_rfc(mod)
        docs, sb, _ = loaded_docs(root)
        key = ("payroll_core", "rfc", "")
        loc, doc = docs[key]
        eff = Status.SUPERSEDED if key in sb else doc.status
        data = json.loads(render_json(loc, doc, eff))
        self.assertEqual(data["kind"], "rfc")
        self.assertEqual(data["module"], "payroll_core")
        self.assertEqual(data["status"], "draft")
        self.assertEqual(data["effective_status"], "draft")
        self.assertEqual(data["implementation"], "implemented")


class ValidateTest(unittest.TestCase):
    def test_valid_tree(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_rfc(mod)
        _sample_decision(mod, "0001")
        _sample_plan(mod, "0001")
        self.assertEqual(validate(root), [])

    def test_broken_ref(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_rfc(mod)  # refs rfc/0001 which does not exist
        problems = validate(root)
        self.assertTrue(any("ref to missing doc" in p for p in problems))

    def test_broken_supersedes(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_decision(mod, "0002", supersedes="0001")  # 0001 does not exist
        problems = validate(root)
        self.assertTrue(any("ref to missing doc" in p for p in problems))

    def test_kind_mismatch(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        (mod / "__rfc__.py").write_text(
            'from pydacc.spec import user_doc\n'
            f'DOC = user_doc(module="{mod.name}", title="wrong kind")\n'
        )
        problems = validate(root)
        self.assertTrue(any("content kind" in p for p in problems))

    def test_missing_required_section(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        (mod / "__rfc__.py").write_text(
            "from pydacc.spec import rfc, Section, Status\n"
            f'RFC = rfc(module="{mod.name}", title="bare", status=Status.DRAFT,'
            ' sections=(Section("Мотивация", "body"),))\n'
        )
        problems = validate(root)
        self.assertTrue(any("missing required section" in p for p in problems))

    def test_cancelled_must_not_supersede(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_decision(mod, "0001")
        (mod / "rfc" / "0002.py").write_text(
            "from pydacc.spec import rfc, Section, Status, ref\n"
            f'RFC = rfc(module="{mod.name}", title="gone", status=Status.CANCELLED,'
            f' {SECTIONS_PY}, supersedes=(ref("{mod.name}", "rfc", "0001"),))\n'
        )
        problems = validate(root)
        self.assertTrue(any("CANCELLED must not supersede" in p for p in problems))

    def test_supersedes_cycle(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_decision(mod, "0001")
        (mod / "rfc" / "0001.py").write_text(
            "from pydacc.spec import rfc, Section, Status, ref\n"
            f'RFC = rfc(module="{mod.name}", title="loop", status=Status.ACCEPTED,'
            f' {SECTIONS_PY}, supersedes=(ref("{mod.name}", "rfc", "0002"),))\n'
        )
        (mod / "rfc" / "0002.py").write_text(
            "from pydacc.spec import rfc, Section, Status, ref\n"
            f'RFC = rfc(module="{mod.name}", title="loop2", status=Status.ACCEPTED,'
            f' {SECTIONS_PY}, supersedes=(ref("{mod.name}", "rfc", "0001"),))\n'
        )
        problems = validate(root)
        self.assertTrue(any("cycle" in p for p in problems))


class LifecycleTest(unittest.TestCase):
    def test_effective_superseded(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_decision(mod, "0001")
        _sample_decision(mod, "0002", supersedes="0001")
        self.assertEqual(_eff(root, "rfc", "0001"), Status.SUPERSEDED)
        self.assertEqual(_eff(root, "rfc", "0002"), Status.ACCEPTED)

    def test_status_report_marks_superseded(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_decision(mod, "0001")
        _sample_decision(mod, "0002", supersedes="0001")
        out = status_report(root)
        self.assertIn("superseded", out)

    def test_graph_report_chain(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_decision(mod, "0001")
        _sample_decision(mod, "0002", supersedes="0001")
        out = graph_report(root, "payroll_core")
        self.assertIn("supersedes: payroll_core::rfc/0001", out)
        self.assertIn("superseded_by: payroll_core::rfc/0002", out)

    def test_warning_accepted_references_draft(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_rfc(mod, status="DRAFT")
        _sample_decision(mod, "0001")  # accepted, no references — no warning
        self.assertEqual(warnings(root), [])
        # now an accepted decision references the draft contract
        (mod / "rfc" / "0001.py").write_text(
            "from pydacc.spec import rfc, Section, Status, ref\n"
            f'RFC = rfc(module="{mod.name}", title="Pick mechanism", status=Status.ACCEPTED,'
            f' {SECTIONS_PY}, references=(ref("{mod.name}", "rfc", ""),))\n'
        )
        self.assertTrue(any("references draft" in w for w in warnings(root)))


class FreshnessTest(unittest.TestCase):
    def test_user_md_stale_when_missing(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_user(mod)
        self.assertTrue(any("user.md" in p for p in freshness(root)))

    def test_user_md_fresh(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_user(mod)
        docs, sb, _ = loaded_docs(root)
        key = ("payroll_core", "user", "")
        loc, doc = docs[key]
        eff = Status.SUPERSEDED if key in sb else doc.status
        (mod / "docs" / "user.md").write_text(render_md(loc, doc, eff))
        self.assertEqual(freshness(root), [])


if __name__ == "__main__":
    unittest.main()
