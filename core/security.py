from typing import Callable

MAX_COMMAND_LENGTH = 4_000

def is_command_risky(command: str) -> bool:
    """Shell commands are always impactful and require explicit approval."""
    return bool(command and command.strip())


def validate_command(command: str) -> tuple[bool, str]:
    if not isinstance(command, str) or not command.strip():
        return False, "Komut boş olamaz."
    if "\x00" in command:
        return False, "Komut geçersiz bir NUL karakteri içeriyor."
    if len(command) > MAX_COMMAND_LENGTH:
        return False, "Komut izin verilen uzunluğu aşıyor."
    return True, ""

def request_approval(command: str, ui_callback: Callable[[str], bool]) -> bool:
    valid, _ = validate_command(command)
    if not valid:
        return False
    return bool(ui_callback(
        "⚠️ Misha terminal komutu çalıştırmak istiyor:\n\n"
        f"{command}\n\nBu komutu çalıştırmasına izin veriyor musunuz?"
    ))
