from __future__ import annotations

import argparse
import json
import math
import platform
import re
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Sequence

import psutil  # type: ignore


def _battery_snapshot() -> dict[str, object]:
    battery = psutil.sensors_battery()
    if battery is None:
        return {"available": False}
    return {
        "available": True,
        "percent": round(float(battery.percent), 1),
        "plugged_in": bool(battery.power_plugged),
        "seconds_left": int(battery.secsleft),
    }


def _safe_diagnostics(stderr: str) -> list[str]:
    allowed = re.compile(
        r"^(?:whisper_print_timings:|whisper_model_load: (?:model size|CPU total size)|"
        r"whisper_init_with_params_no_state: use gpu|whisper_backend_init)"
    )
    return [line.strip()[:240] for line in stderr.splitlines() if allowed.match(line.strip())][-30:]


def _synthetic_wav(path: Path, duration_seconds: float = 5.0) -> None:
    sample_count = round(16_000 * duration_seconds)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"".join(
            struct.pack("<h", round(30 * math.sin(2 * math.pi * 220 * index / 16_000)))
            for index in range(sample_count)
        ))


def profile_command(command: list[str], *, sample_seconds: float = 0.05) -> dict[str, object]:
    battery_before = _battery_snapshot()
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    child = psutil.Process(process.pid)
    peak_rss = 0
    cpu_seconds = 0.0
    while process.poll() is None:
        try:
            peak_rss = max(peak_rss, child.memory_info().rss)
            cpu_times = child.cpu_times()
            cpu_seconds = max(cpu_seconds, float(cpu_times.user + cpu_times.system))
        except (psutil.Error, OSError):
            pass
        time.sleep(max(0.01, min(float(sample_seconds), 0.5)))
    stderr = (process.communicate()[1] or "")[-20_000:]
    elapsed = max(time.monotonic() - started, 0.000_001)
    try:
        cpu_times = child.cpu_times()
        cpu_seconds = max(cpu_seconds, float(cpu_times.user + cpu_times.system))
    except (psutil.Error, OSError):
        pass
    return {
        "schema_version": 1,
        "system": platform.system(),
        "machine": platform.machine(),
        "returncode": int(process.returncode or 0),
        "wall_seconds": round(elapsed, 3),
        "cpu_seconds": round(cpu_seconds, 3),
        "average_cpu_percent_one_core_100": round(cpu_seconds / elapsed * 100, 1),
        "peak_rss_mib": round(peak_rss / 1024 / 1024, 1),
        "battery_before": battery_before,
        "battery_after": _battery_snapshot(),
        "diagnostics": _safe_diagnostics(stderr),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profile the local Misha Whisper runtime.")
    parser.add_argument("--whisper-cli", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--no-gpu", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    cli = args.whisper_cli.expanduser().resolve()
    model = args.model.expanduser().resolve()
    if not cli.is_file() or not model.is_file():
        parser.error("whisper-cli and model must be existing files")
    with tempfile.TemporaryDirectory(prefix="misha-voice-profile-") as directory:
        audio = args.audio.expanduser().resolve() if args.audio else Path(directory) / "synthetic.wav"
        if args.audio is None:
            _synthetic_wav(audio)
        if not audio.is_file() or audio.suffix.casefold() != ".wav":
            parser.error("audio must be an existing WAV file")
        command = [str(cli)]
        if args.no_gpu:
            command.append("--no-gpu")
        command.extend([
            "--threads", "4", "--model", str(model), "--file", str(audio),
            "--language", "tr", "--no-timestamps", "--output-txt",
            "--output-file", str(Path(directory) / "transcript"),
        ])
        report = profile_command(command)
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["returncode"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
