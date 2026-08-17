from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class DocumentationClaimsTests(unittest.TestCase):
    def test_public_docs_link_to_explicit_feature_boundaries(self):
        readme = (ROOT / "readme.md").read_text(encoding="utf-8")
        guide = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
        status = (ROOT / "docs" / "FEATURE_STATUS.md").read_text(encoding="utf-8")

        self.assertIn("docs/FEATURE_STATUS.md", readme)
        self.assertIn("FEATURE_STATUS.md", guide)
        for required_boundary in (
            "Live Google/Microsoft integrations",
            "Automatic updates",
            "Native macOS distribution",
            "Hands-free wake and owner voice gate",
        ):
            self.assertIn(required_boundary, status)

    def test_public_docs_do_not_claim_zero_error_or_completed_external_acceptance(self):
        public_docs = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                ROOT / "readme.md",
                ROOT / "docs" / "USER_GUIDE.md",
                ROOT / "docs" / "RELEASE_NOTES_0.1.0.md",
            )
        ).casefold()
        for forbidden_claim in (
            "zero error",
            "sıfır hata garantisi",
            "notarization complete",
            "notarization tamamlandı",
            "live google integration is available",
        ):
            self.assertNotIn(forbidden_claim, public_docs)


if __name__ == "__main__":
    unittest.main()
