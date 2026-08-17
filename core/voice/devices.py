from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


DeviceKind = Literal["input", "output"]


class AudioDeviceError(RuntimeError):
    """Raised when no compatible local audio device can be selected."""


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    input_channels: int
    output_channels: int
    default_sample_rate: int
    is_default_input: bool = False
    is_default_output: bool = False


class AudioDeviceManager:
    """Enumerates and safely resolves local PortAudio devices."""

    def __init__(self, backend: Any | None = None, sample_rate: int = 16000) -> None:
        if sample_rate < 8000:
            raise ValueError("Sample rate must be at least 8000 Hz.")
        if backend is None:
            try:
                import sounddevice as backend
            except ImportError as exc:
                raise AudioDeviceError(
                    "The local audio-device dependency is not installed."
                ) from exc
        self.backend = backend
        self.sample_rate = int(sample_rate)

    def _default_indices(self) -> tuple[int | None, int | None]:
        raw = getattr(getattr(self.backend, "default", None), "device", None)
        try:
            return self._as_index(raw[0]), self._as_index(raw[1])
        except (IndexError, KeyError, TypeError):
            pass
        index = self._as_index(raw)
        return index, index

    @staticmethod
    def _as_index(value: Any) -> int | None:
        try:
            index = int(value)
        except (TypeError, ValueError):
            return None
        return index if index >= 0 else None

    def list_devices(self, kind: DeviceKind | None = None) -> list[AudioDevice]:
        default_input, default_output = self._default_indices()
        devices: list[AudioDevice] = []
        for index, raw in enumerate(self.backend.query_devices()):
            input_channels = int(raw.get("max_input_channels", 0) or 0)
            output_channels = int(raw.get("max_output_channels", 0) or 0)
            if kind == "input" and input_channels < 1:
                continue
            if kind == "output" and output_channels < 1:
                continue
            devices.append(
                AudioDevice(
                    index=index,
                    name=str(raw.get("name") or f"Audio device {index}"),
                    input_channels=input_channels,
                    output_channels=output_channels,
                    default_sample_rate=int(float(raw.get("default_samplerate") or 0)),
                    is_default_input=index == default_input,
                    is_default_output=index == default_output,
                )
            )
        return devices

    def supports(self, device: AudioDevice, kind: DeviceKind) -> bool:
        try:
            if kind == "input":
                if device.input_channels < 1:
                    return False
                self.backend.check_input_settings(
                    device=device.index,
                    channels=1,
                    samplerate=self.sample_rate,
                    dtype="float32",
                )
            else:
                if device.output_channels < 1:
                    return False
                self.backend.check_output_settings(
                    device=device.index,
                    channels=1,
                    samplerate=self.sample_rate,
                    dtype="float32",
                )
            return True
        except Exception:
            return False

    def resolve(
        self,
        kind: DeviceKind,
        *,
        preferred_index: int | None = None,
        preferred_name: str | None = None,
    ) -> AudioDevice:
        devices = self.list_devices(kind)
        if not devices:
            raise AudioDeviceError(f"No local {kind} audio device is available.")

        candidates: list[AudioDevice] = []
        if preferred_index is not None:
            candidates.extend(d for d in devices if d.index == preferred_index)
        normalized_name = (preferred_name or "").strip().casefold()
        if normalized_name:
            candidates.extend(d for d in devices if d.name.casefold() == normalized_name)
            candidates.extend(d for d in devices if normalized_name in d.name.casefold())
        default_attr = "is_default_input" if kind == "input" else "is_default_output"
        candidates.extend(d for d in devices if getattr(d, default_attr))
        candidates.extend(devices)

        seen: set[int] = set()
        for candidate in candidates:
            if candidate.index in seen:
                continue
            seen.add(candidate.index)
            if self.supports(candidate, kind):
                return candidate
        raise AudioDeviceError(
            f"No {kind} device supports mono {self.sample_rate} Hz float audio."
        )

    def resolve_input(
        self,
        preferred_index: int | None = None,
        preferred_name: str | None = None,
    ) -> AudioDevice:
        return self.resolve(
            "input",
            preferred_index=preferred_index,
            preferred_name=preferred_name,
        )

    def resolve_output(
        self,
        preferred_index: int | None = None,
        preferred_name: str | None = None,
    ) -> AudioDevice:
        return self.resolve(
            "output",
            preferred_index=preferred_index,
            preferred_name=preferred_name,
        )
