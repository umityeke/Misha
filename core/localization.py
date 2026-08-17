from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from memory.config_manager import get_config


SUPPORTED_LANGUAGES = {"tr", "en"}
_TEXT = {
    "tr": {
        "settings_saved": "Ayarlar kaydedildi.",
        "safe_failure": "İşlem güvenli biçimde tamamlanamadı.",
        "permission_required": "Bu işlem için izin gerekiyor.",
    },
    "en": {
        "settings_saved": "Settings saved.",
        "safe_failure": "The operation could not be completed safely.",
        "permission_required": "This action requires permission.",
    },
}


def configured_ui_language() -> str:
    try:
        language = (get_config("ui_language") or "tr").strip().casefold()
    except Exception:
        language = "tr"
    return language if language in SUPPORTED_LANGUAGES else "tr"


def configured_response_language() -> str:
    try:
        language = (get_config("response_language") or "auto").strip().casefold()
    except Exception:
        language = "auto"
    return language if language in SUPPORTED_LANGUAGES | {"auto"} else "auto"


def translate(key: str, *, language: str | None = None) -> str:
    selected = (language or configured_ui_language()).casefold()
    if selected not in SUPPORTED_LANGUAGES:
        selected = "tr"
    return _TEXT[selected].get(key, key)


def response_language_instruction() -> str:
    language = configured_response_language()
    if language == "tr":
        return "Always respond to the owner in clear Turkish. Preserve code and proper nouns."
    if language == "en":
        return "Always respond to the owner in clear English. Preserve code and proper nouns."
    return "Respond in the language used by the owner in the latest request."


def localized_datetime(
    value: datetime,
    *,
    timezone_name: str = "Europe/Istanbul",
    language: str | None = None,
) -> str:
    try:
        local_value = value.astimezone(ZoneInfo(timezone_name))
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Unsupported timezone.") from exc
    selected = (language or configured_ui_language()).casefold()
    if selected == "en":
        return local_value.strftime("%Y-%m-%d %H:%M %Z")
    return local_value.strftime("%d.%m.%Y %H:%M %Z")


def safe_error_message(code: str, *, detail: str = "") -> str:
    base = translate("safe_failure")
    normalized = "_".join(str(code).strip().casefold().split()) or "unknown"
    suffix = f" {detail.strip()}" if detail.strip() else ""
    return f"{base} [{normalized}]{suffix}"
