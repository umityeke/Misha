from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from core.ai.ollama import OllamaProvider
from core.ai.provider import AIProvider, GenerationRequest
from memory.config_manager import get_config


DEFAULT_LOCAL_MODEL = "qwen3-coder:30b"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"


@lru_cache(maxsize=4)
def _ollama_provider(
    model: str,
    base_url: str,
    fallback_models: tuple[str, ...] = (),
) -> OllamaProvider:
    return OllamaProvider(
        model=model,
        base_url=base_url,
        fallback_models=fallback_models,
    )


def _configured_fallback_models() -> tuple[str, ...]:
    raw = (get_config("local_model_fallbacks") or "[]").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in raw.split(",") if item.strip()]
    if not isinstance(parsed, list):
        return ()
    result = []
    for item in parsed:
        name = str(item).strip()
        if name and len(name) <= 128 and name not in result:
            result.append(name)
    return tuple(result[:4])


def get_provider() -> AIProvider:
    provider_name = (get_config("ai_provider") or "ollama").strip().lower()
    if provider_name != "ollama":
        raise RuntimeError(
            f"Unsupported AI provider: {provider_name}. Misha is configured for local Ollama."
        )
    model = (get_config("local_model") or DEFAULT_LOCAL_MODEL).strip()
    base_url = (get_config("ollama_base_url") or DEFAULT_OLLAMA_URL).strip()
    parsed_url = urlparse(base_url)
    if (
        parsed_url.scheme != "http"
        or parsed_url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        raise RuntimeError("Ollama must use a local-only address.")
    fallbacks = tuple(
        candidate
        for candidate in _configured_fallback_models()
        if candidate != model
    )
    return _ollama_provider(model, base_url, fallbacks)


def _runtime_options(options: dict[str, Any] | None) -> dict[str, Any]:
    try:
        raw_context = get_config("local_context_length") or "8192"
    except Exception:
        raw_context = "8192"
    try:
        context_length = int(raw_context)
    except (TypeError, ValueError):
        context_length = 8192
    context_length = max(2048, min(context_length, 32768))
    return {"num_ctx": context_length, **(options or {})}


def generate_text(
    prompt: str,
    *,
    system: str = "",
    temperature: float = 0.2,
    options: dict[str, Any] | None = None,
) -> str:
    from core.localization import response_language_instruction

    language_rule = response_language_instruction()
    localized_system = f"{system.strip()}\n\nLanguage policy: {language_rule}".strip()
    request = GenerationRequest(
        prompt=prompt,
        system=localized_system,
        temperature=temperature,
        options=_runtime_options(options),
    )
    return get_provider().generate(request)


def _extract_json(text: str) -> Any:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(cleaned):
            if char not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(cleaned[index:])
                return value
            except json.JSONDecodeError:
                continue
        raise


def generate_json(
    prompt: str,
    *,
    system: str = "",
    temperature: float = 0.1,
    options: dict[str, Any] | None = None,
) -> Any:
    from core.localization import response_language_instruction

    language_rule = response_language_instruction()
    localized_system = f"{system.strip()}\n\nLanguage policy: {language_rule}".strip()
    request = GenerationRequest(
        prompt=prompt,
        system=localized_system,
        temperature=temperature,
        json_mode=True,
        options=_runtime_options(options),
    )
    return _extract_json(get_provider().generate(request))


def release_provider_memory() -> None:
    """Free local model RAM before another on-device model needs it."""
    get_provider().unload()
