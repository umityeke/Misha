from __future__ import annotations

import subprocess
import unittest
from unittest.mock import Mock, patch

from scripts.profile_voice_runtime import profile_command


class VoiceProfilerTests(unittest.TestCase):
    def test_profile_is_bounded_and_reports_only_resource_metadata(self):
        process = Mock()
        process.pid = 42
        process.poll.side_effect = [None, 0]
        process.communicate.return_value = ("", "safe diagnostic")
        process.returncode = 0
        child = Mock()
        child.memory_info.return_value.rss = 10 * 1024 * 1024
        child.cpu_times.return_value = Mock(user=0.2, system=0.1)
        with patch("scripts.profile_voice_runtime.subprocess.Popen", return_value=process) as popen, patch(
            "scripts.profile_voice_runtime.psutil.Process", return_value=child
        ), patch(
            "scripts.profile_voice_runtime._battery_snapshot",
            side_effect=[{"available": False}, {"available": False}],
        ), patch("scripts.profile_voice_runtime.time.sleep"):
            report = profile_command(["/safe/whisper-cli", "--model", "/safe/model.bin"])
        self.assertEqual(report["returncode"], 0)
        self.assertEqual(report["peak_rss_mib"], 10.0)
        self.assertNotIn("stdout", report)
        self.assertNotIn("stderr_tail", report)
        self.assertEqual(popen.call_args.args[0][0], "/safe/whisper-cli")
        self.assertFalse(popen.call_args.kwargs.get("shell", False))


if __name__ == "__main__":
    unittest.main()
