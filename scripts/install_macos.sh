#!/bin/zsh
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  print -u2 "This installer is only for macOS."
  exit 1
fi

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
cd "$PROJECT_DIR"

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.11 || true)}"
if [[ -z "$PYTHON_BIN" ]]; then
  print -u2 "Python 3.11 is required. Install it with: brew install python@3.11"
  exit 1
fi

if [[ ! -x "venv/bin/python" ]]; then
  "$PYTHON_BIN" -m venv venv
fi

venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements.txt
venv/bin/python -m playwright install chromium

for command_name in ollama whisper-cli; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    print -u2 "Missing required command: $command_name"
  fi
done

if ! command -v ffmpeg >/dev/null 2>&1; then
  print "Optional FFmpeg is missing. Install it with: brew install ffmpeg"
fi

venv/bin/python -m scripts.doctor
