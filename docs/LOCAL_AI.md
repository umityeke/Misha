# Misha Local Intelligence

Misha's active intelligence path is local-only. It does not require a Gemini,
Claude, OpenAI, or other paid API key.

## Runtime

- Provider: Ollama on `127.0.0.1`
- Default model: `qwen3-coder:30b`
- Default context: 8,192 tokens
- Configuration: `~/.misha/config.db` with file mode `0600`
- Learned rules: `~/.misha/learning.db` with file mode `0600`

The Ollama endpoint is restricted to localhost during normal configuration.
Remote configuration sync is disabled unless
`MISHA_REMOTE_CONFIG_ENABLED=1` is explicitly set.

## First run

```bash
ollama pull qwen3-coder:30b
ollama list
python main.py
```

The desktop setup screen stores the selected local model. It never asks for a
paid-provider API key.

## Local voice setup on macOS

Install `whisper.cpp`, place the multilingual model outside the repository, and
run the owner enrollment module:

```bash
brew install whisper-cpp
mkdir -p ~/.misha/models
# Expected model: ~/.misha/models/ggml-large-v3-turbo-q5_0.bin
venv/bin/python -m scripts.setup_local_voice
```

Enrollment records three six-second samples locally. The temporary recordings
are deleted after the voice profile is written. Restart Misha and use
`CLICK TO SPEAK`; no recording is sent to a network service.

The enrollment command lists local microphones and lets the owner select one.
Misha stores both the device name and current PortAudio index in the private
local config. At startup and before each recording it validates mono 16 kHz
support; if an index changes or the device disappears, it resolves the saved
name and then safely falls back to the current system-default microphone.

Push-to-talk uses an offline energy VAD instead of a fixed recording duration.
It keeps a short pre-roll, requires sustained speech to reject transient noise,
stops after trailing silence, supports cancellation, and enforces a bounded
maximum recording time. Threshold calibration against the owner's real room
and microphone remains part of enrollment acceptance testing.

After PIN unlock and owner enrollment, hands-free mode listens locally for
VAD-bounded utterances. Speaker verification runs before transcription and only
the verified owner's `Misha`/`Mişa` wake phrase can dispatch a command. Saying the
wake phrase alone opens an eight-second follow-up window. Temporary WAV files
are deleted after inspection; unrelated and non-owner speech is not dispatched.

The packaged macOS app has passed a real no-button acceptance path: owner speech
triggered VAD, local Whisper wake transcription, local agent execution, and
macOS speech output, then returned to listening without a crash.

## Safety boundaries

- The planner may select only registered tools.
- Plans are limited to five steps.
- Risky tools fail closed if no approval callback exists.
- Unknown tools and generated-code fallback execution are rejected.
- Generated project paths cannot escape their workspace.
- Generated run commands use a small executable allowlist.
- Secrets, passwords, tokens, and API keys cannot be stored as learned rules.
- A missing local vision model disables visual analysis instead of falling back
  to a cloud service.

## Learning model

Misha improves through inspectable user-taught rules and reusable skills. It
does not modify model weights or silently rewrite its own production code.
Self-modifications must be developed in an isolated branch, tested, reviewed,
and made rollback-safe before activation.

## Current limitation

Text planning and coding are local. The active runtime also has a local voice
foundation:

- `whisper.cpp` performs offline multilingual speech recognition.
- macOS `say` performs offline speech synthesis.
- Owner enrollment stores a private local voice profile with mode `0600`.
- Speaker matching is a convenience gate only. PIN and explicit approval remain
  mandatory for risky actions.

Custom low-power wake-model training, enrollment UI, microphone permission
onboarding, and measured Turkish accuracy/latency are still pending. The old cloud voice
implementation remains in the source temporarily but is unreachable from the
active runtime.
