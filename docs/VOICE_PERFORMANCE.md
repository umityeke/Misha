# Voice performance baseline

The profiler runs `whisper-cli` as an argv-only child process and records wall time,
CPU time, peak resident memory and battery state. It never records a microphone and
does not retain transcript text. Its default fixture is five seconds of synthetic,
near-silent PCM audio.

## 2026-08-17 Apple arm64 baseline

The local `large-v3-turbo-q5_0` model completed the five-second CPU-only fixture in
about 7.4 seconds, using about 30.3 CPU-seconds (407% of one core) and 861 MiB peak
RSS. The machine was charging, so this run cannot establish battery-drain acceptance.
The managed test session could not allocate the Metal buffer; GPU and unplugged
battery measurements therefore remain release acceptance work.

The machine-readable, path-redacted result is written to
`quality-artifacts/voice-profile.json`. Re-run it with:

```bash
python scripts/profile_voice_runtime.py \
  --whisper-cli /opt/homebrew/bin/whisper-cli \
  --model ~/.misha/models/ggml-large-v3-turbo-q5_0.bin \
  --output quality-artifacts/voice-profile.json
```

Do not claim a battery or GPU target from the CPU fallback result. Run on battery and
with Metal available, record ambient conditions, and compare the same fixture before
closing the release gate.
