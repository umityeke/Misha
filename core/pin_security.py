import base64
import hashlib
import hmac
import secrets
from memory.config_manager import get_config, set_config

PBKDF2_ITERATIONS = 600_000
_PREFIX = "pbkdf2_sha256"


def _hash_pin(pin: str, *, salt: bytes | None = None) -> str:
    """Derive a salted, deliberately expensive verifier for a four-digit PIN."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return "$".join((
        _PREFIX,
        str(PBKDF2_ITERATIONS),
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    ))

def is_pin_set() -> bool:
    """Checks if a PIN has been set in the database."""
    return bool(get_config("hashed_pin"))

def set_pin(pin: str) -> bool:
    """Store a new PIN verifier only when the PIN has the expected format."""
    if len(pin) != 4 or not pin.isdigit():
        return False
    return bool(set_config("hashed_pin", _hash_pin(pin)))

def verify_pin(pin: str) -> bool:
    """Verifies if the provided PIN matches the saved hash in the database."""
    saved_hash = get_config("hashed_pin")
    if not saved_hash:
        return False
    try:
        prefix, iterations, salt_text, digest_text = saved_hash.split("$", 3)
        if prefix != _PREFIX:
            raise ValueError("Unsupported PIN verifier")
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256", pin.encode("utf-8"), salt, int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        # One-time compatibility with the legacy unsalted SHA-256 verifier.
        legacy = hashlib.sha256(pin.encode("utf-8")).hexdigest()
        verified = hmac.compare_digest(legacy, saved_hash)
        if verified:
            set_pin(pin)
        return verified
