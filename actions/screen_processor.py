from __future__ import annotations

from core.ai.runtime import generate_text, get_provider


_SYSTEM_PROMPT = (
    "You are MISHA's private, local screen assistant. Analyze only the supplied "
    "macOS accessibility text. Never claim to see pixels, images, or controls that "
    "are not present in that text. Be concise and state uncertainty explicitly."
)


def _write(player, message: str) -> None:
    if player is not None and hasattr(player, "write_log"):
        player.write_log(message)
    print(f"[Vision] {message}")


def _active_window_text() -> str:
    try:
        from core.macos_observe import get_active_window_text

        return (get_active_window_text() or "").strip()
    except Exception as exc:
        print(f"[Vision] Native Observe failed: {exc}")
        return ""


def screen_process(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> bool:
    """Analyze accessible screen text using only the local Ollama provider."""
    params = parameters or {}
    user_text = (params.get("text") or params.get("user_text") or "").strip()
    angle = str(params.get("angle", "screen")).lower().strip()

    if not user_text:
        _write(player, "SYS: Screen analysis needs a question.")
        return False
    if angle != "screen":
        _write(
            player,
            "SYS: Camera/image analysis is unavailable until a local vision model is configured.",
        )
        return False

    window_text = _active_window_text()
    if not window_text:
        _write(
            player,
            "SYS: No accessible active-window text was found; no cloud service was called.",
        )
        return False

    prompt = (
        f"User question:\n{user_text}\n\n"
        f"Accessible active-window text:\n{window_text[:16000]}"
    )
    try:
        answer = generate_text(prompt, system=_SYSTEM_PROMPT, temperature=0.1)
    except Exception as exc:
        _write(player, f"SYS: Local screen analysis failed: {exc}")
        return False

    _write(player, f"Misha: {answer.strip()}")
    return True


def warmup_session(player=None) -> None:
    """Check the local text provider without opening a network/cloud session."""
    ready, message = get_provider().healthcheck()
    if not ready:
        _write(player, f"SYS: Local screen analysis is not ready: {message}")
