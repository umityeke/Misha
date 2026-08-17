# Voice performance baseline

The profiler runs `whisper-cli` as an argv-only child process and records wall time,
CPU time, peak resident memory and battery state. It never records a microphone and
does not retain transcript text. Its default fixture is five seconds of synthetic,
near-silent PCM audio.

## 2026-08-17 Apple arm64 baseline

The local `large-v3-turbo-q5_0` model completed the five-second CPU-only fixture in
7.505 seconds, using 30.375 CPU-seconds (404.7% of one core) and 857.5 MiB peak RSS.
The machine was charging, so this run cannot establish battery-drain acceptance.
The same fixture exposed a native Metal-path `SIGSEGV`; the product transcriber now
retries exactly once with `--no-gpu` after that signal and keeps backend diagnostics
out of user-facing errors. GPU and unplugged battery measurements remain release
acceptance work.

The machine-readable, path-redacted result is written to
`quality-artifacts/voice-profile.json`. Re-run it with:

```bash
python scripts/profile_voice_runtime.py \
  --whisper-cli /opt/homebrew/bin/whisper-cli \
  --model ~/.misha/models/ggml-large-v3-turbo-q5_0.bin \
  --no-gpu \
  --output quality-artifacts/voice-profile.json
```

Do not claim a battery or GPU target from the CPU fallback result. Run on battery and
with Metal available, record ambient conditions, and compare the same fixture before
closing the release gate.
