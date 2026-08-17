from __future__ import annotations

import json
import random
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.ai.provider import GenerationRequest, ProviderError, ProviderErrorKind


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: int = 180,
        max_attempts: int = 3,
        initial_backoff_seconds: float = 0.4,
        maximum_backoff_seconds: float = 3.0,
        jitter_ratio: float = 0.25,
        fallback_models: tuple[str, ...] = (),
    ) -> None:
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_attempts = max(1, min(int(max_attempts), 5))
        self.initial_backoff_seconds = max(0.0, float(initial_backoff_seconds))
        self.maximum_backoff_seconds = max(
            self.initial_backoff_seconds,
            float(maximum_backoff_seconds),
        )
        self.jitter_ratio = max(0.0, min(float(jitter_ratio), 1.0))
        self.fallback_models = tuple(
            candidate.strip()
            for candidate in fallback_models[:4]
            if candidate.strip() and candidate.strip() != self.model
        )
        self.active_model = self.model
        if not self.model:
            raise ValueError("A local Ollama model must be configured.")
        candidates = (self.model, *self.fallback_models)
        if any(
            candidate.casefold().endswith("-cloud")
            or ":cloud" in candidate.casefold()
            for candidate in candidates
        ):
            raise ValueError("Ollama cloud model aliases are disabled in local-only mode.")

    def _request(self, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429:
                error = ProviderError(
                    ProviderErrorKind.RATE_LIMIT,
                    "The local model is busy. Please try again shortly.",
                    retryable=True,
                    status_code=exc.code,
                )
            elif exc.code in {408, 425} or exc.code >= 500:
                error = ProviderError(
                    ProviderErrorKind.SERVER,
                    "The local model service is temporarily unavailable.",
                    retryable=True,
                    status_code=exc.code,
                )
            elif exc.code in {401, 403}:
                error = ProviderError(
                    ProviderErrorKind.AUTH,
                    "The local model service rejected access.",
                    retryable=False,
                    status_code=exc.code,
                )
            else:
                error = ProviderError(
                    ProviderErrorKind.REQUEST,
                    f"The local model rejected the request (HTTP {exc.code}).",
                    retryable=False,
                    status_code=exc.code,
                )
            raise error from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise ProviderError(
                    ProviderErrorKind.TIMEOUT,
                    "The local model did not respond in time.",
                    retryable=True,
                ) from exc
            raise ProviderError(
                ProviderErrorKind.OFFLINE,
                "Ollama is not reachable. Start the Ollama application and try again.",
                retryable=True,
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ProviderError(
                ProviderErrorKind.TIMEOUT,
                "The local model did not respond in time.",
                retryable=True,
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE,
                "The local model returned an invalid response.",
                retryable=True,
            ) from exc

    def _retry_delay(self, retry_index: int) -> float:
        base = min(
            self.maximum_backoff_seconds,
            self.initial_backoff_seconds * (2 ** max(0, retry_index)),
        )
        return base + random.uniform(0.0, base * self.jitter_ratio)

    def _request_with_retry(self, path: str, payload: dict) -> dict:
        last_error: ProviderError | None = None
        for attempt in range(self.max_attempts):
            try:
                return self._request(path, payload)
            except ProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt + 1 >= self.max_attempts:
                    raise
                time.sleep(self._retry_delay(attempt))
        if last_error is not None:
            raise last_error
        raise ProviderError(
            ProviderErrorKind.UNKNOWN,
            "The local model request failed.",
            retryable=False,
        )

    def healthcheck(self) -> tuple[bool, str]:
        try:
            payload = self._request("/api/tags")
            installed = {
                value
                for item in payload.get("models", [])
                for value in (item.get("name", ""), item.get("model", ""))
                if value
            }
            candidates = (self.model, *self.fallback_models)
            for candidate in candidates:
                if candidate not in installed:
                    continue
                details = self._request("/api/show", {"model": candidate})
                capabilities = {
                    str(value).strip().lower()
                    for value in details.get("capabilities", [])
                }
                if "completion" not in capabilities:
                    continue
                self.active_model = candidate
                if candidate == self.model:
                    return True, f"Ollama is ready with {candidate}."
                return True, (
                    f"Primary local model is unavailable; using local fallback {candidate}."
                )
            if any(candidate in installed for candidate in candidates):
                return False, "Installed local model does not support text completion."
            return False, (
                "No configured local model is installed: " + ", ".join(candidates)
            )
        except Exception as exc:
            return False, str(exc)

    def generate(self, request: GenerationRequest) -> str:
        request_options = dict(request.options)
        think = request_options.pop("think", None)
        if think is not None and not isinstance(think, bool):
            raise ValueError("Ollama think option must be a boolean.")
        payload = {
            "model": self.active_model,
            "prompt": request.prompt,
            "system": request.system,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                **request_options,
            },
        }
        if think is not None:
            payload["think"] = think
        if request.json_mode:
            payload["format"] = "json"
        response = {}
        for attempt in range(3):
            response = self._request_with_retry("/api/generate", payload)
            text = str(response.get("response", "")).strip()
            if text:
                return text
            if response.get("done") is not False:
                break
            time.sleep(0.5 * (attempt + 1))
        raise RuntimeError("The local model returned an empty response.")

    def unload(self) -> None:
        self._request(
            "/api/generate",
            {"model": self.active_model, "keep_alive": 0, "stream": False},
        )
