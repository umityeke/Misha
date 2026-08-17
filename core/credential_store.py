from __future__ import annotations

import ctypes
import getpass
import os
import platform
import shutil
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path


KEYCHAIN_SERVICE_PREFIX = "com.umityeke.misha"
_ERR_SEC_ITEM_NOT_FOUND = -25300
_SECURITY_PATH = "/System/Library/Frameworks/Security.framework/Security"
_CORE_FOUNDATION_PATH = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"


class CredentialStoreError(RuntimeError):
    pass


def _require_macos() -> None:
    if platform.system() != "Darwin":
        raise CredentialStoreError(
            "Secure credential storage is not configured for this operating system."
        )


def _service(name: str) -> str:
    normalized = str(name).strip().lower().replace("_", "-")
    if not normalized or not all(ch.isalnum() or ch in "-." for ch in normalized):
        raise ValueError("Credential name contains unsupported characters.")
    return f"{KEYCHAIN_SERVICE_PREFIX}.{normalized}"


def _account() -> str:
    return getpass.getuser() or "misha-owner"


def _frameworks():
    try:
        security = ctypes.CDLL(_SECURITY_PATH)
        core_foundation = ctypes.CDLL(_CORE_FOUNDATION_PATH)
    except OSError as exc:
        raise CredentialStoreError("macOS Keychain is unavailable.") from exc

    security.SecKeychainFindGenericPassword.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32,
        ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
    ]
    security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    security.SecKeychainCopyDefault.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    security.SecKeychainCopyDefault.restype = ctypes.c_int32
    security.SecKeychainAddGenericPassword.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32,
        ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ]
    security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
    security.SecKeychainItemModifyContent.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
    ]
    security.SecKeychainItemModifyContent.restype = ctypes.c_int32
    security.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
    security.SecKeychainItemDelete.restype = ctypes.c_int32
    security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    security.SecKeychainItemFreeContent.restype = ctypes.c_int32
    core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
    return security, core_foundation


def _default_keychain(security):
    keychain = ctypes.c_void_p()
    if security.SecKeychainCopyDefault(ctypes.byref(keychain)) != 0 or not keychain:
        raise CredentialStoreError("macOS default Keychain is unavailable.")
    return keychain


def _find_raw(name: str):
    security, core_foundation = _frameworks()
    keychain = _default_keychain(security)
    service = _service(name).encode("utf-8")
    account = _account().encode("utf-8")
    length = ctypes.c_uint32()
    data = ctypes.c_void_p()
    item = ctypes.c_void_p()
    try:
        status = security.SecKeychainFindGenericPassword(
            keychain, len(service), service, len(account), account,
            ctypes.byref(length), ctypes.byref(data), ctypes.byref(item),
        )
    finally:
        core_foundation.CFRelease(keychain)
    if status == _ERR_SEC_ITEM_NOT_FOUND:
        return security, core_foundation, None, None
    if status != 0:
        raise CredentialStoreError("macOS Keychain could not read the requested credential.")
    try:
        value = ctypes.string_at(data, length.value)
    finally:
        security.SecKeychainItemFreeContent(None, data)
    return security, core_foundation, value, item


def _release(core_foundation, item) -> None:
    if item:
        core_foundation.CFRelease(item)


def _macos_get_secret(name: str) -> str | None:
    _require_macos()
    _security, core_foundation, value, item = _find_raw(name)
    if value is None:
        return None
    try:
        decoded = value.decode("utf-8")
        if not decoded:
            raise CredentialStoreError("macOS Keychain returned an empty credential.")
        return decoded
    except UnicodeDecodeError as exc:
        raise CredentialStoreError("macOS Keychain returned an invalid credential.") from exc
    finally:
        _release(core_foundation, item)


def _macos_set_secret(name: str, value: str) -> None:
    _require_macos()
    secret = str(value)
    if not secret:
        raise ValueError("Credential value cannot be empty.")
    security, core_foundation, _existing, item = _find_raw(name)
    secret_bytes = bytearray(secret.encode("utf-8"))
    buffer = (ctypes.c_ubyte * len(secret_bytes)).from_buffer(secret_bytes)
    try:
        if item:
            status = security.SecKeychainItemModifyContent(item, None, len(secret_bytes), buffer)
        else:
            service = _service(name).encode("utf-8")
            account = _account().encode("utf-8")
            new_item = ctypes.c_void_p()
            keychain = _default_keychain(security)
            try:
                status = security.SecKeychainAddGenericPassword(
                    keychain, len(service), service, len(account), account,
                    len(secret_bytes), buffer, ctypes.byref(new_item),
                )
            finally:
                core_foundation.CFRelease(keychain)
            _release(core_foundation, new_item)
        if status != 0:
            raise CredentialStoreError("macOS Keychain could not store the credential.")
    finally:
        _release(core_foundation, item)
        for index in range(len(secret_bytes)):
            secret_bytes[index] = 0


def _macos_delete_secret(name: str) -> bool:
    _require_macos()
    security, core_foundation, value, item = _find_raw(name)
    if value is None:
        return False
    try:
        if security.SecKeychainItemDelete(item) != 0:
            raise CredentialStoreError("macOS Keychain could not delete the credential.")
        return True
    finally:
        _release(core_foundation, item)


def _windows_api():
    if not hasattr(ctypes, "WinDLL"):
        raise CredentialStoreError("Windows Credential Manager is unavailable.")
    from ctypes import wintypes

    class Credential(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    api.CredReadW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(Credential)),
    ]
    api.CredReadW.restype = wintypes.BOOL
    api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    return api, Credential


def _windows_get_secret(name: str) -> str | None:
    api, credential_type = _windows_api()
    pointer = ctypes.POINTER(credential_type)()
    if not api.CredReadW(_service(name), 1, 0, ctypes.byref(pointer)):
        error = ctypes.get_last_error()
        if error == 1168:  # ERROR_NOT_FOUND
            return None
        raise CredentialStoreError("Windows Credential Manager could not read the credential.")
    try:
        credential = pointer.contents
        raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        try:
            decoded = raw.decode("utf-16-le")
        except UnicodeDecodeError as exc:
            raise CredentialStoreError(
                "Windows Credential Manager returned an invalid credential."
            ) from exc
        if not decoded:
            raise CredentialStoreError("Windows Credential Manager returned an empty credential.")
        return decoded
    finally:
        api.CredFree(pointer)


def _windows_set_secret(name: str, value: str) -> None:
    from ctypes import wintypes

    api, credential_type = _windows_api()
    secret_bytes = bytearray(value.encode("utf-16-le"))
    if len(secret_bytes) > 2560:
        raise ValueError("Credential value exceeds the Windows secure-store limit.")
    blob = (ctypes.c_ubyte * len(secret_bytes)).from_buffer(secret_bytes)
    credential = credential_type()
    credential.Type = 1  # CRED_TYPE_GENERIC
    credential.TargetName = _service(name)
    credential.CredentialBlobSize = len(secret_bytes)
    credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE (current user's profile)
    credential.UserName = _account()
    try:
        if not api.CredWriteW(ctypes.byref(credential), wintypes.DWORD(0)):
            raise CredentialStoreError("Windows Credential Manager could not store the credential.")
    finally:
        for index in range(len(secret_bytes)):
            secret_bytes[index] = 0


def _windows_delete_secret(name: str) -> bool:
    api, _credential_type = _windows_api()
    if api.CredDeleteW(_service(name), 1, 0):
        return True
    if ctypes.get_last_error() == 1168:
        return False
    raise CredentialStoreError("Windows Credential Manager could not delete the credential.")


def _secret_tool() -> str:
    executable = shutil.which("secret-tool")
    if not executable:
        raise CredentialStoreError(
            "Linux Secret Service requires the system 'secret-tool' client."
        )
    return executable


def _linux_get_secret(name: str) -> str | None:
    try:
        result = subprocess.run(
            [_secret_tool(), "lookup", "service", _service(name), "account", _account()],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CredentialStoreError("Linux Secret Service could not read the credential.") from exc
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise CredentialStoreError("Linux Secret Service could not read the credential.")
    value = result.stdout.rstrip("\r\n")
    if not value:
        raise CredentialStoreError("Linux Secret Service returned an empty credential.")
    return value


def _linux_set_secret(name: str, value: str) -> None:
    try:
        result = subprocess.run(
            [
                _secret_tool(), "store", "--label", "Misha local credential",
                "service", _service(name), "account", _account(),
            ],
            input=value, capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CredentialStoreError("Linux Secret Service could not store the credential.") from exc
    if result.returncode != 0:
        raise CredentialStoreError("Linux Secret Service could not store the credential.")


def _linux_delete_secret(name: str) -> bool:
    existing = _linux_get_secret(name)
    if existing is None:
        return False
    try:
        result = subprocess.run(
            [_secret_tool(), "clear", "service", _service(name), "account", _account()],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CredentialStoreError("Linux Secret Service could not delete the credential.") from exc
    if result.returncode != 0:
        raise CredentialStoreError("Linux Secret Service could not delete the credential.")
    return True


def get_secret(name: str) -> str | None:
    system = platform.system()
    if system == "Darwin":
        return _macos_get_secret(name)
    if system == "Windows":
        return _windows_get_secret(name)
    if system == "Linux":
        return _linux_get_secret(name)
    raise CredentialStoreError("Secure credential storage is unsupported on this operating system.")


def set_secret(name: str, value: str) -> None:
    secret = str(value)
    if not secret:
        raise ValueError("Credential value cannot be empty.")
    system = platform.system()
    if system == "Darwin":
        _macos_set_secret(name, secret)
    elif system == "Windows":
        _windows_set_secret(name, secret)
    elif system == "Linux":
        _linux_set_secret(name, secret)
    else:
        raise CredentialStoreError("Secure credential storage is unsupported on this operating system.")


def delete_secret(name: str) -> bool:
    system = platform.system()
    if system == "Darwin":
        return _macos_delete_secret(name)
    if system == "Windows":
        return _windows_delete_secret(name)
    if system == "Linux":
        return _linux_delete_secret(name)
    raise CredentialStoreError("Secure credential storage is unsupported on this operating system.")


def get_or_create_secret(name: str, factory: Callable[[], str]) -> str:
    existing = get_secret(name)
    if existing is not None:
        return existing
    generated = str(factory())
    if not generated:
        raise ValueError("Credential factory returned an empty value.")
    set_secret(name, generated)
    stored = get_secret(name)
    if stored != generated:
        raise CredentialStoreError("Credential could not be verified after Keychain write.")
    return stored


def migrate_dotenv_secret(path: str | Path, variable: str, credential_name: str) -> bool:
    """Move one legacy dotenv value to Keychain, then atomically remove its line."""
    env_path = Path(path).expanduser().resolve()
    if not env_path.is_file():
        return False
    prefix = f"{variable}="
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    candidates = [line.rstrip("\r\n")[len(prefix):] for line in lines if line.startswith(prefix)]
    value = next((item.strip() for item in reversed(candidates) if item.strip()), "")
    if not value:
        return False
    set_secret(credential_name, value)
    if get_secret(credential_name) != value:
        raise CredentialStoreError("Credential migration verification failed.")
    retained = [line for line in lines if not line.startswith(prefix)]
    temporary = env_path.with_name(f".{env_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text("".join(retained), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(env_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return True
