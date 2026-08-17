# config/__init__.py
import platform

def get_config() -> dict:
    from memory.config_manager import get_config as get_value
    return {"os_system": get_value("os_system") or _platform_default()}

def _platform_default() -> str:
    return {"Windows": "windows", "Darwin": "mac"}.get(platform.system(), "linux")

def get_os() -> str:
    """Returns: 'windows' | 'mac' | 'linux'"""
    return get_config().get("os_system", "windows").lower()

def is_windows() -> bool: return get_os() == "windows"
def is_mac()     -> bool: return get_os() == "mac"
def is_linux()   -> bool: return get_os() == "linux"
