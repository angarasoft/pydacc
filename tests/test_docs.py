import tempfile
import unittest
from pathlib import Path

from pydacc.docs import discover, freshness, load, render_json, render_md, validate


def _write_module(root: Path, module: str, layer: str = "base") -> Path:
    mod = root / "addons" / layer / module
    mod.mkdir(parents=True)
    return mod


def _sample_rfc(mod: Path) -> None:
    (mod / "__rfc__.py").write_text(
        "from pydacc.spec import rfc, Section, Status, ref\n"
        f'RFC = rfc(module="{mod.name}", title="Payroll Engine", status=Status.DRAFT,'
        ' summary="s", sections=(Section("why", "body"),), invariants=("i1",),'
        ' references=(ref("payroll_core", "adr", "0001"),))\n'
    )


def _sample_adr(mod: Path, ident: str) -> None:
    adr_dir = mod / "__adr__"
    adr_dir.mkdir()
    (adr_dir / f"{ident}.py").write_text(
        "from pydacc.spec import adr, Status\n"
        f'ADR = adr(module="{mod.name}", title="Pick mechanism", status=Status.ACCEPTED,'
        ' summary="why")\n'
    )


def _sample_user(mod: Path) -> None:
    d = mod / "docs"
    d.mkdir()
    (d / "user.py").write_text(
        "from pydacc.spec import user_doc, Section\n"
        f'DOC = user_doc(module="{mod.name}", title="How to use",'
        ' sections=(Section("Step 1", "do this"),))\n'
    )


class DiscoverTest(unittest.TestCase):
    def test_finds_all_kinds(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_rfc(mod)
        _sample_adr(mod, "0001")
        _sample_user(mod)
        located = discover(root)
        kinds = sorted(l.kind for l in located)
        self.assertEqual(kinds, ["adr", "rfc", "user"])

    def test_no_addons(self):
        root = Path(tempfile.mkdtemp())
        self.assertEqual(discover(root), [])


class LoadTest(unittest.TestCase):
    def test_load_rfc(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_rfc(mod)
        loc = next(l for l in discover(root) if l.kind == "rfc")
        doc = load(root, loc)
        self.assertEqual(doc.title, "Payroll Engine")
        self.assertEqual(doc.module, "payroll_core")

    def test_adr_ident_from_filename(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_adr(mod, "0042")
        loc = next(l for l in discover(root) if l.kind == "adr")
        self.assertEqual(load(root, loc).ident, "0042")


class RenderTest(unittest.TestCase):
    def test_render_md(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_rfc(mod)
        loc = next(l for l in discover(root) if l.kind == "rfc")
        out = render_md(loc, load(root, loc))
        self.assertIn("# Payroll Engine", out)
        self.assertIn("## why", out)
        self.assertIn("## Инварианты", out)
        self.assertIn("`payroll_core::adr/0001`", out)

    def test_render_json(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_rfc(mod)
        loc = next(l for l in discover(root) if l.kind == "rfc")
        import json

        data = json.loads(render_json(loc, load(root, loc)))
        self.assertEqual(data["kind"], "rfc")
        self.assertEqual(data["module"], "payroll_core")
        self.assertEqual(data["status"], "draft")


class ValidateTest(unittest.TestCase):
    def test_valid_tree(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_rfc(mod)
        _sample_adr(mod, "0001")
        self.assertEqual(validate(root), [])

    def test_broken_ref(self):
        root = Path(tempfile.mkdtemp())
        mod = _write_module(root, "payroll_core")
        _sample_rfc(mod)  # refs adr/0001 which does not exist
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
        loc = next(l for l in discover(root) if l.kind == "user")
        (mod / "docs" / "user.md").write_text(render_md(loc, load(root, loc)))
        self.assertEqual(freshness(root), [])


if __name__ == "__main__":
    unittest.main()
