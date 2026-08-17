import unittest

from scripts.scan_secrets import scan_text


class SecretScannerTests(unittest.TestCase):
    def test_reports_without_returning_secret_value(self):
        token = "ghp_" + ("a" * 36)
        findings = scan_text("demo.py", f"TOKEN={token}")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule, "github_token")
        self.assertNotIn(token, repr(findings[0]))

    def test_allowlist_comment_suppresses_false_positive(self):
        url = "postgresql" + "://demo:password@example.test/db"
        findings = scan_text(
            "example.py", f"URL={url}  # pragma: allowlist secret"
        )
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
