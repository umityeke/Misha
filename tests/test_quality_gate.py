from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from scripts import quality_gate


class QualityGateTests(unittest.TestCase):
    def test_command_set_contains_every_required_local_gate(self):
        with patch.object(quality_gate, "_resolve_command", return_value="/usr/bin/pyright"):
            commands = quality_gate.gate_commands("/usr/bin/python3", pytest_mode=False)
        self.assertEqual(
            [name for name, _command in commands],
            ["compile", "lint", "type-check", "tests", "secret-scan"],
        )
        self.assertNotIn("shell", " ".join(part for _name, command in commands for part in command))

    def test_pytest_mode_writes_bounded_artifact_paths(self):
        with patch.object(quality_gate, "_resolve_command", return_value="pyright"):
            commands = dict(quality_gate.gate_commands("python", pytest_mode=True))
        self.assertIn("--junitxml=quality-artifacts/junit.xml", commands["tests"])
        self.assertIn("--cov-report=xml:quality-artifacts/coverage.xml", commands["tests"])

    def test_failed_command_is_redacted_to_exception_type(self):
        with tempfile.TemporaryDirectory(dir=quality_gate.ROOT) as directory:
            with patch("scripts.quality_gate.subprocess.run", side_effect=OSError("private path")):
                result = quality_gate.run_gate("compile", ["missing"], Path(directory))
            self.assertEqual(result.status, "failed")
            self.assertNotIn("private path", (Path(directory) / "compile.log").read_text())

    def test_gate_streams_to_regular_file_and_bounds_log(self):
        def fake_run(command, **kwargs):
            stream = kwargs["stdout"]
            self.assertFalse(kwargs.get("capture_output", False))
            stream.write("old\n" + ("x" * (quality_gate.MAX_LOG_BYTES + 100)))
            return CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory(dir=quality_gate.ROOT) as directory:
            with patch("scripts.quality_gate.subprocess.run", side_effect=fake_run):
                result = quality_gate.run_gate("tests", ["python", "-m", "unittest"], Path(directory))
            log = (Path(directory) / "tests.log").read_bytes()
            self.assertEqual(result.status, "passed")
            self.assertTrue(log.startswith(quality_gate._TRUNCATION_MARKER))
            self.assertLessEqual(len(log), quality_gate.MAX_LOG_BYTES + len(quality_gate._TRUNCATION_MARKER))

    def test_main_writes_machine_readable_summary(self):
        with tempfile.TemporaryDirectory(dir=quality_gate.ROOT) as directory:
            passed = quality_gate.GateResult("compile", ["python"], "passed", 0, 0.1, "compile.log")
            with (
                patch.object(
                    quality_gate,
                    "gate_commands",
                    return_value=[
                        ("compile", ["python"]),
                        ("lint", ["ruff"]),
                        ("type-check", ["pyright"]),
                        ("tests", ["python"]),
                        ("secret-scan", ["python"]),
                    ],
                ),
                patch.object(quality_gate, "run_gate", return_value=passed),
            ):
                self.assertEqual(quality_gate.main(["--artifact-dir", directory]), 0)
            summary = json.loads((Path(directory) / "summary.json").read_text())
            self.assertTrue(summary["passed"])
            self.assertEqual(len(summary["results"]), 5)


if __name__ == "__main__":
    unittest.main()
