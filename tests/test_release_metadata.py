from __future__ import annotations

import plistlib
import unittest
from pathlib import Path

from core.version import APP_VERSION, BUILD_NUMBER, UPDATE_CHANNEL, version_label


ROOT = Path(__file__).resolve().parent.parent


class ReleaseMetadataTests(unittest.TestCase):
    def test_semantic_version_build_and_channel_are_explicit(self):
        self.assertRegex(APP_VERSION, r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
        self.assertGreaterEqual(BUILD_NUMBER, 1)
        self.assertIn(UPDATE_CHANNEL, {"stable", "beta"})
        self.assertIn(APP_VERSION, version_label())
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'version = "{APP_VERSION}"', pyproject)

    def test_spec_bundle_metadata_matches_runtime_version(self):
        spec = (ROOT / "Misha.spec").read_text(encoding="utf-8")
        self.assertIn(f"'CFBundleShortVersionString': '{APP_VERSION}'", spec)
        self.assertIn(f"'CFBundleVersion': '{BUILD_NUMBER}'", spec)
        self.assertIn("platform_excludes", spec)
        self.assertIn("non_runtime_excludes", spec)
        self.assertIn('"cv2"', spec)
        self.assertIn('"psycopg2"', spec)
        self.assertIn("'NSAppleEventsUsageDescription'", spec)
        self.assertIn("Mail ve Takvim", spec)

    def test_entitlements_are_minimal_and_do_not_disable_security(self):
        entitlements = plistlib.loads(
            (ROOT / "packaging/macos/entitlements.plist").read_bytes()
        )
        self.assertEqual(entitlements, {})
        development = plistlib.loads(
            (ROOT / "packaging/macos/entitlements-development.plist").read_bytes()
        )
        self.assertEqual(
            development, {"com.apple.security.cs.disable-library-validation": True}
        )
        source = (ROOT / "docs/MACOS_ENTITLEMENTS.md").read_text(encoding="utf-8")
        self.assertIn("A Developer ID release must use the empty production", source)

    def test_signing_script_uses_inside_out_hardened_runtime(self):
        script = (ROOT / "scripts/sign_macos_bundle.sh").read_text(encoding="utf-8")
        self.assertIn("find \"$bundle_path/Contents/Frameworks\"", script)
        self.assertGreaterEqual(script.count("--options runtime"), 2)
        self.assertNotIn("--deep --force", script)


if __name__ == "__main__":
    unittest.main()
