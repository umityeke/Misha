from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionStatus:
    key: str
    label: str
    status: str
    detail: str


_SETTINGS_ROUTES = {
    "microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
    "camera": "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "screen_recording": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
}


def _status_name(value: int) -> str:
    return {0: "not_requested", 1: "restricted", 2: "denied", 3: "granted"}.get(
        int(value), "unknown"
    )


def _media_status(media_type: str, framework_attribute: str) -> str:
    try:
        import AVFoundation

        value = int(
            AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
                getattr(AVFoundation, framework_attribute)
            )
        )
    except Exception:
        try:
            import objc

            objc.loadBundle(
                "AVFoundation", globals(),
                bundle_path="/System/Library/Frameworks/AVFoundation.framework",
            )
            device = objc.lookUpClass("AVCaptureDevice")
            value = int(device.authorizationStatusForMediaType_(media_type))
        except Exception:
            return "unknown"
    return _status_name(value)


def get_permission_statuses() -> tuple[PermissionStatus, ...]:
    if sys.platform != "darwin":
        return tuple(
            PermissionStatus(key, label, "not_applicable", "macOS only")
            for key, label in (
                ("microphone", "Microphone"),
                ("camera", "Camera"),
                ("accessibility", "Accessibility"),
                ("screen_recording", "Screen recording"),
            )
        )
    microphone = _media_status("soun", "AVMediaTypeAudio")
    camera = _media_status("vide", "AVMediaTypeVideo")
    try:
        import ApplicationServices

        accessibility = (
            "granted" if ApplicationServices.AXIsProcessTrusted() else "denied"
        )
    except Exception:
        accessibility = "unknown"
    try:
        import Quartz

        screen_recording = (
            "granted" if Quartz.CGPreflightScreenCaptureAccess() else "denied"
        )
    except Exception:
        screen_recording = "unknown"
    return (
        PermissionStatus("microphone", "Microphone", microphone, "Hands-free voice input"),
        PermissionStatus("camera", "Camera", camera, "Optional local camera analysis"),
        PermissionStatus("accessibility", "Accessibility", accessibility, "Active-window text and computer control"),
        PermissionStatus("screen_recording", "Screen recording", screen_recording, "Optional visual screen capture"),
    )


def open_permission_settings(permission: str) -> bool:
    key = str(permission).strip().casefold()
    route = _SETTINGS_ROUTES.get(key)
    if sys.platform != "darwin" or route is None:
        return False
    try:
        subprocess.run(
            ["open", route], check=True, timeout=5,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False
