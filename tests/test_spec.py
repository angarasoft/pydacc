import unittest

from pydacc.spec import Section, Status, adr, ref, rfc, user_doc


class SpecTest(unittest.TestCase):
    def test_rfc_defaults(self):
        doc = rfc(module="m", title="t", status=Status.DRAFT)
        self.assertEqual(doc.kind, "rfc")
        self.assertEqual(doc.status, Status.DRAFT)
        self.assertEqual(doc.sections, ())

    def test_status_accepts_string(self):
        self.assertEqual(rfc("m", "t", "accepted").status, Status.ACCEPTED)

    def test_status_rejects_unknown(self):
        with self.assertRaises(ValueError):
            rfc("m", "t", "nope")

    def test_adr_ident_defaults_empty(self):
        doc = adr(module="m", title="t", status=Status.ACCEPTED)
        self.assertEqual(doc.ident, "")

    def test_sections_and_refs(self):
        doc = rfc(
            module="m",
            title="t",
            status="draft",
            sections=(Section("s", "body"),),
            references=(ref("other", "adr", "0001"),),
        )
        self.assertEqual(doc.sections[0].title, "s")
        self.assertEqual(doc.references[0].module, "other")

    def test_user_doc_status_accepted(self):
        self.assertEqual(user_doc("m", "t").status, Status.ACCEPTED)


if __name__ == "__main__":
    unittest.main()
