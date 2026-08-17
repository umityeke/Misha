#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This installer is only for Linux." >&2
  exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
cd "$project_dir"

python_bin="${MISHA_PYTHON_BIN:-}"
if [[ -z "$python_bin" ]]; then
  python_bin="$(command -v python3.11 || command -v python3.12 || command -v python3.13 || true)"
fi
if [[ -z "$python_bin" ]]; then
  echo "Python 3.11-3.13 is required." >&2
  exit 1
fi

if [[ ! -x "venv/bin/python" ]]; then
  "$python_bin" -m venv venv
fi
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements.txt
venv/bin/python -m playwright install chromium

for command_name in ollama whisper-cli; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
  fi
done
if ! command -v secret-tool >/dev/null 2>&1; then
  echo "Linux Secret Service client is missing; secure credential features will fail closed." >&2
fi
venv/bin/python -m scripts.doctor
