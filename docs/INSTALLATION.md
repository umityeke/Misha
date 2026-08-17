# Misha Installation

## Native development bundle

1. Use macOS 13 or newer on Apple Silicon.
2. Install Ollama and download `qwen3-coder:30b`.
3. Install `whisper.cpp` and place the documented model under `~/.misha/models/`.
4. Open `dist/Misha.app` and complete the local PIN, privacy guide and setup checks.
5. Grant Microphone and Accessibility only when the corresponding Misha feature is used.

The current bundle is ad-hoc signed for local development. It is not a notarized public
installer. Do not bypass Gatekeeper for a bundle obtained from an untrusted source.

## Source installation

```bash
python3.11 -m venv venv
venv/bin/python -m pip install -r requirements.txt
venv/bin/python -m scripts.doctor
venv/bin/python main.py
```

For acceptance, run `venv/bin/python scripts/quality_gate.py` and confirm every gate
passes. Private application data is stored outside the source tree and must not be
copied from unknown archives.
