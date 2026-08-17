from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARTIFACT_DIR = ROOT / "quality-artifacts"


@dataclass(frozen=True)
class GateResult:
    name: str
    command: list[str]
    status: str
    returncode: int | None
    duration_seconds: float
    log: str


def _resolve_command(candidates: Sequence[str]) -> str | None:
    for candidate in candidates:
        if os.path.isabs(candidate) and Path(candidate).is_file():
            return candidate
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def gate_commands(python: str, *, pytest_mode: bool) -> list[tuple[str, list[str]]]:
    pyright = _resolve_command(["pyright", "/opt/homebrew/bin/pyright"])
    commands: list[tuple[str, list[str]]] = [
        (
            "compile",
            [python, "-m", "compileall", "-q", "actions", "agent", "core", "memory", "scripts"],
        )
    ]
    commands.append(
        (
            "lint",
            [
                python,
                "-m",
                "flake8",
                "actions",
                "agent",
                "core",
                "memory",
                "scripts",
                "tests",
                "--select=E9,F63,F7,F82",
                "--exclude=dist,build,work,misha-vscode,venv",
            ],
        )
    )
    if pyright:
        commands.append(("type-check", [pyright, "--project", "pyrightconfig.json"]))
    if pytest_mode:
        commands.append(
            (
                "tests",
                [
                    python,
                    "-m",
                    "pytest",
                    "-m",
                    "not slow",
                    "--junitxml=quality-artifacts/junit.xml",
                    "--cov",
                    "--cov-report=xml:quality-artifacts/coverage.xml",
                    "--cov-report=term",
                ],
            )
        )
    else:
        commands.append(("tests", [python, "-m", "unittest", "discover", "-s", "tests", "-v"]))
    commands.append(("secret-scan", [python, "scripts/scan_secrets.py"]))
    return commands


def run_gate(name: str, command: list[str], artifact_dir: Path) -> GateResult:
    started = time.monotonic()
    log_path = artifact_dir / f"{name}.log"
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=600,
            check=False,
        )
        output = completed.stdout[-2_000_000:]
        log_path.write_text(output, encoding="utf-8")
        return GateResult(
            name=name,
            command=command,
            status="passed" if completed.returncode == 0 else "failed",
            returncode=completed.returncode,
            duration_seconds=round(time.monotonic() - started, 3),
            log=str(log_path.relative_to(ROOT)),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        safe_error = f"{type(error).__name__}: quality command could not complete\n"
        log_path.write_text(safe_error, encoding="utf-8")
        return GateResult(
            name=name,
            command=command,
            status="failed",
            returncode=None,
            duration_seconds=round(time.monotonic() - started, 3),
            log=str(log_path.relative_to(ROOT)),
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Misha's deterministic local quality gates.")
    parser.add_argument(
        "--pytest", action="store_true", help="Use pytest with JUnit and coverage output."
    )
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    args = parser.parse_args(argv)

    artifact_dir = args.artifact_dir.resolve()
    if artifact_dir != ROOT / "quality-artifacts" and ROOT not in artifact_dir.parents:
        parser.error("artifact directory must remain inside the project")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    commands = gate_commands(sys.executable, pytest_mode=args.pytest)
    required = {"compile", "lint", "type-check", "tests", "secret-scan"}
    available = {name for name, _command in commands}
    missing = sorted(required - available)
    results = [run_gate(name, command, artifact_dir) for name, command in commands]
    for name in missing:
        results.append(GateResult(name, [], "failed", None, 0.0, "quality tool is not installed"))

    summary = {
        "schema_version": 1,
        "passed": not missing and all(result.status == "passed" for result in results),
        "results": [asdict(result) for result in results],
    }
    (artifact_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for result in results:
        print(f"[{result.status.upper()}] {result.name} ({result.duration_seconds:.3f}s)")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
