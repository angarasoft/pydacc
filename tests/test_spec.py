import unittest

from pydacc.spec import Implementation, RFC_SECTIONS, Section, Status, plan, ref, rfc, user_doc


class SpecTest(unittest.TestCase):
    def test_rfc_defaults(self):
        doc = rfc(module="m", title="t", status=Status.DRAFT)
        self.assertEqual(doc.kind, "rfc")
        self.assertEqual(doc.status, Status.DRAFT)
        self.assertEqual(doc.sections, ())
        self.assertIsNone(doc.implementation)

    def test_plan_kind(self):
        doc = plan(module="m", title="t", status="draft")
        self.assertEqual(doc.kind, "plan")
        self.assertEqual(doc.status, Status.DRAFT)

    def test_status_accepts_string(self):
        self.assertEqual(rfc("m", "t", "accepted").status, Status.ACCEPTED)

    def test_status_rejects_unknown(self):
        with self.assertRaises(ValueError):
            rfc("m", "t", "nope")

    def test_cancelled_status(self):
        self.assertEqual(rfc("m", "t", "cancelled").status, Status.CANCELLED)

    def test_implementation_axis(self):
        doc = rfc("m", "t", "draft", implementation=Implementation.IMPLEMENTED)
        self.assertEqual(doc.implementation, Implementation.IMPLEMENTED)

    def test_implementation_accepts_string(self):
        self.assertEqual(
            rfc("m", "t", "draft", implementation="planned").implementation,
            Implementation.PLANNED,
        )

    def test_implementation_rejects_unknown(self):
        with self.assertRaises(ValueError):
            rfc("m", "t", "draft", implementation="nope")

    def test_required_sections_constant(self):
        self.assertEqual(RFC_SECTIONS[0], "Резюме")
        self.assertIn("Change Log", RFC_SECTIONS)

    def test_sections_and_refs(self):
        doc = rfc(
            module="m",
            title="t",
            status="draft",
            sections=(Section("s", "body"),),
            references=(ref("other", "rfc", "0001"),),
        )
        self.assertEqual(doc.sections[0].title, "s")
        self.assertEqual(doc.references[0].module, "other")
        self.assertEqual(doc.references[0].kind, "rfc")

    def test_user_doc_status_accepted(self):
        self.assertEqual(user_doc("m", "t").status, Status.ACCEPTED)

    def test_supersedes(self):
        old = ref("m", "rfc", "0001")
        doc = rfc(module="m", title="new", status="accepted", supersedes=(old,))
        self.assertEqual(doc.supersedes, (old,))

    def test_supersedes_default_empty(self):
        self.assertEqual(rfc("m", "t", "draft").supersedes, ())


if __name__ == "__main__":
    unittest.main()
