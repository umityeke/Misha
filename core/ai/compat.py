from __future__ import annotations

from dataclasses import dataclass

from core.ai.runtime import generate_text


@dataclass(frozen=True)
class LocalTextResponse:
    text: str


class LocalTextModel:
    """Small compatibility adapter for legacy text-only model call sites."""

    def __init__(self, system_instruction: str = "") -> None:
        self.system_instruction = system_instruction

    def generate_content(self, content) -> LocalTextResponse:
        if isinstance(content, str):
            prompt = content
        elif isinstance(content, (list, tuple)) and all(
            isinstance(item, str) for item in content
        ):
            prompt = "\n\n".join(content)
        else:
            raise RuntimeError(
                "This operation requires a local vision model. No cloud API was called."
            )
        return LocalTextResponse(
            generate_text(prompt, system=self.system_instruction, temperature=0.2)
        )
