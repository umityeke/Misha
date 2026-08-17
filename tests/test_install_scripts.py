from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import doctor


ROOT = Path(__file__).resolve().parent.parent


class InstallScriptTests(unittest.TestCase):
    def test_linux_installer_is_strict_quoted_and_runs_doctor(self):
        script = (ROOT / "scripts/install_linux.sh").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", script)
        self.assertIn('cd "$project_dir"', script)
        self.assertIn("-m scripts.doctor", script)
        self.assertNotIn("curl |", script)
        self.assertNotIn("eval ", script)

    def test_windows_installer_is_strict_and_uses_argument_invocation(self):
        script = (ROOT / "scripts/install_windows.ps1").read_text(encoding="utf-8")
        self.assertIn('$ErrorActionPreference = "Stop"', script)
        self.assertIn("Set-StrictMode", script)
        self.assertIn("& $VenvPython -m scripts.doctor", script)
        self.assertNotIn("Invoke-Expression", script)

    def test_doctor_requires_only_the_current_platform_bridge(self):
        with patch("scripts.doctor.platform.system", return_value="Linux"), patch(
            "scripts.doctor.check_import",
            side_effect=lambda module, label=None: doctor.DoctorCheck(module, True, True, label or module),
        ) as check_import, patch("scripts.doctor.check_command", return_value=doctor.DoctorCheck("cmd", True, True, "ok")), patch(
            "scripts.doctor.check_file", return_value=doctor.DoctorCheck("file", True, True, "ok")
        ), patch("scripts.doctor.check_private_file", return_value=doctor.DoctorCheck("private", True, True, "ok")), patch(
            "scripts.doctor.check_local_configuration", return_value=[]
        ):
            doctor.run_checks(services=False, audio=False)
        modules = [call.args[0] for call in check_import.call_args_list]
        self.assertIn("pynput", modules)
        self.assertNotIn("AppKit", modules)


if __name__ == "__main__":
    unittest.main()
