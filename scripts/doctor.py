from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable


DEFAULT_MODEL = "qwen3-coder:30b"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_WHISPER_MODEL = Path.home() / ".misha/models/ggml-large-v3-turbo-q5_0.bin"
DEFAULT_VOICE_PROFILE = Path.home() / ".misha/voice/owner.json"


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    required: bool
    message: str


def check_python(version_info: tuple[int, ...] | None = None) -> DoctorCheck:
    version = version_info or tuple(sys.version_info[:3])
    supported = (3, 11) <= version[:2] < (3, 14)
    rendered = ".".join(str(part) for part in version[:3])
    return DoctorCheck(
        "python",
        supported,
        True,
        f"Python {rendered}" if supported else f"Python {rendered}; 3.11-3.13 required",
    )


def check_import(module: str, label: str | None = None) -> DoctorCheck:
    available = importlib.util.find_spec(module) is not None
    name = label or module
    return DoctorCheck(
        f"import:{module}",
        available,
        True,
        f"{name} importable" if available else f"{name} missing; reinstall project dependencies",
    )


def check_command(
    name: str,
    *,
    required: bool,
    alternatives: Iterable[str] = (),
) -> DoctorCheck:
    candidates = (name, *alternatives)
    executable = next((shutil.which(item) for item in candidates if shutil.which(item)), None)
    return DoctorCheck(
        f"command:{name}",
        executable is not None,
        required,
        executable or f"{name} not found on PATH",
    )


def check_file(name: str, path: Path, *, required: bool) -> DoctorCheck:
    exists = path.expanduser().is_file()
    return DoctorCheck(
        f"file:{name}",
        exists,
        required,
        str(path.expanduser()) if exists else f"Missing: {path.expanduser()}",
    )


def check_private_file(name: str, path: Path, *, required: bool) -> DoctorCheck:
    path = path.expanduser()
    if not path.is_file():
        return DoctorCheck(f"privacy:{name}", False, required, f"Missing: {path}")
    if os.name == "posix" and path.stat().st_mode & 0o077:
        return DoctorCheck(
            f"privacy:{name}",
            False,
            required,
            f"Permissions are too broad for {path}; expected 0600",
        )
    return DoctorCheck(f"privacy:{name}", True, required, f"Private permissions: {path}")


def check_local_configuration(
    getter: Callable[[str], str | None] | None = None,
) -> list[DoctorCheck]:
    if getter is None:
        from memory.config_manager import get_config

        getter = get_config
    provider = (getter("ai_provider") or "ollama").strip().lower()
    model = (getter("local_model") or DEFAULT_MODEL).strip()
    base_url = (getter("ollama_base_url") or DEFAULT_OLLAMA_URL).strip().rstrip("/")
    local_url = base_url.startswith(("http://127.0.0.1", "http://localhost"))
    return [
        DoctorCheck(
            "config:provider",
            provider == "ollama",
            True,
            f"AI provider: {provider}",
        ),
        DoctorCheck(
            "config:model",
            bool(model),
            True,
            f"Local model: {model}" if model else "Local model is not configured",
        ),
        DoctorCheck(
            "config:ollama-url",
            local_url,
            True,
            f"Ollama address: {base_url}" if local_url else "Ollama address must remain local-only",
        ),
    ]


def check_ollama_service(
    getter: Callable[[str], str | None] | None = None,
    *,
    timeout: float = 2.0,
) -> DoctorCheck:
    if getter is None:
        from memory.config_manager import get_config

        getter = get_config
    model = (getter("local_model") or DEFAULT_MODEL).strip()
    base_url = (getter("ollama_base_url") or DEFAULT_OLLAMA_URL).strip().rstrip("/")
    if not base_url.startswith(("http://127.0.0.1", "http://localhost")):
        return DoctorCheck("service:ollama", False, True, "Refusing to contact a non-local Ollama address")
    try:
        request = urllib.request.Request(f"{base_url}/api/tags", method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
        names = {item.get("name") for item in payload.get("models", [])}
        ready = model in names or f"{model}:latest" in names
        message = f"Ollama ready with {model}" if ready else f"Ollama is running, but {model} is not installed"
        return DoctorCheck("service:ollama", ready, True, message)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return DoctorCheck("service:ollama", False, True, f"Ollama unavailable: {exc}")


def check_audio_devices() -> list[DoctorCheck]:
    try:
        from core.voice.devices import AudioDeviceManager

        manager = AudioDeviceManager(sample_rate=16000)
        microphone = manager.resolve_input()
        outputs = manager.list_devices("output")
        return [
            DoctorCheck("audio:input", True, True, f"Microphone: {microphone.name}"),
            DoctorCheck(
                "audio:output",
                bool(outputs),
                True,
                f"Output devices: {len(outputs)}" if outputs else "No audio output device found",
            ),
        ]
    except Exception as exc:
        return [DoctorCheck("audio:devices", False, True, f"Audio device check failed: {exc}")]


def run_checks(*, services: bool = True, audio: bool = True) -> list[DoctorCheck]:
    platform_imports = {
        "Darwin": (
            ("AppKit", "macOS Cocoa bridge"),
            ("ApplicationServices", "macOS accessibility bridge"),
        ),
        "Windows": (("pynput", "Windows input bridge"),),
        "Linux": (("pynput", "Linux input bridge"),),
    }.get(platform.system(), ())
    checks = [
        check_python(),
        *(check_import(module, label) for module, label in (
            ("PyQt6", "PyQt6"),
            ("numpy", "NumPy"),
            ("sounddevice", "sounddevice"),
            ("psutil", "psutil"),
            ("playwright", "Playwright"),
            *platform_imports,
        )),
        check_command("ollama", required=True),
        check_command("whisper-cli", required=True),
        check_command("ffmpeg", required=False),
        check_file("whisper-model", DEFAULT_WHISPER_MODEL, required=True),
        check_private_file("voice-profile", DEFAULT_VOICE_PROFILE, required=True),
        *check_local_configuration(),
    ]
    if services:
        checks.append(check_ollama_service())
    if audio:
        checks.extend(check_audio_devices())
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the local Misha environment.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--skip-services", action="store_true", help="Skip the Ollama HTTP health check.")
    parser.add_argument("--skip-audio", action="store_true", help="Skip audio-device enumeration.")
    args = parser.parse_args(argv)
    checks = run_checks(services=not args.skip_services, audio=not args.skip_audio)
    failed = [check for check in checks if check.required and not check.ok]
    if args.json:
        print(json.dumps({"ok": not failed, "checks": [asdict(check) for check in checks]}, ensure_ascii=False, indent=2))
    else:
        for check in checks:
            marker = "OK" if check.ok else ("FAIL" if check.required else "WARN")
            print(f"[{marker}] {check.name}: {check.message}")
        print(f"\nMisha environment: {'READY' if not failed else 'NOT READY'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
