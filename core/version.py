from __future__ import annotations


APP_VERSION = "0.1.0"
BUILD_NUMBER = 1
UPDATE_CHANNEL = "stable"


def version_label() -> str:
    return f"{APP_VERSION} ({BUILD_NUMBER}) {UPDATE_CHANNEL}"
