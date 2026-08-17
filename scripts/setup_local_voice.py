from __future__ import annotations

import tempfile
from pathlib import Path

from core.voice.devices import AudioDeviceManager
from core.voice.identity import LocalVoiceIdentity
from core.voice.recorder import SoundDeviceRecorder
from memory.config_manager import save_local_voice_config, set_config


DEFAULT_CLI = Path("/opt/homebrew/bin/whisper-cli")
DEFAULT_MODEL = Path.home() / ".misha" / "models" / "ggml-large-v3-turbo-q5_0.bin"
DEFAULT_PROFILE = Path.home() / ".misha" / "voice" / "owner.json"


def main() -> None:
    print("MISHA — local owner voice enrollment")
    print("Record in a quiet room and speak naturally in Turkish.")
    if not DEFAULT_CLI.is_file():
        raise SystemExit("whisper-cli is missing. Install whisper-cpp first.")
    if not DEFAULT_MODEL.is_file():
        raise SystemExit(f"Whisper model is missing: {DEFAULT_MODEL}")

    device_manager = AudioDeviceManager(sample_rate=16000)
    inputs = device_manager.list_devices("input")
    if not inputs:
        raise SystemExit("Kullanılabilir mikrofon bulunamadı.")
    print("\nKullanılabilir mikrofonlar:")
    for device in inputs:
        marker = " (varsayılan)" if device.is_default_input else ""
        print(f"  [{device.index}] {device.name}{marker}")
    raw_choice = input("Mikrofon numarası [varsayılan]: ").strip()
    preferred_index = None
    if raw_choice:
        try:
            preferred_index = int(raw_choice)
        except ValueError as exc:
            raise SystemExit("Mikrofon numarası geçerli bir sayı olmalı.") from exc
    microphone = device_manager.resolve_input(preferred_index=preferred_index)
    recorder = SoundDeviceRecorder(
        device_manager=device_manager,
        preferred_input_index=microphone.index,
        preferred_input_name=microphone.name,
    )
    set_config("audio_input_device_id", str(microphone.index))
    set_config("audio_input_device_name", microphone.name)
    print(f"Seçilen mikrofon: {microphone.name}")
    identity = LocalVoiceIdentity(DEFAULT_PROFILE)
    prompts = [
        "Misha, bugün üzerinde çalışacağımız projeyi aç.",
        "Misha, yaptığın işlemlerde güvenliğe dikkat et.",
        "Misha, bu bilgisayarda yalnızca benim komutlarımı dinle.",
    ]

    with tempfile.TemporaryDirectory(prefix="misha-enroll-") as temp_dir:
        samples = []
        for index, prompt in enumerate(prompts, start=1):
            input(f"\n[{index}/3] Enter'a bas ve şunu doğal sesinle söyle:\n{prompt}\n")
            path = Path(temp_dir) / f"sample-{index}.wav"
            recorder.record(path, seconds=6.0)
            samples.append(path)
            print("Kayıt alındı.")
        identity.enroll(samples)

    save_local_voice_config(str(DEFAULT_CLI), str(DEFAULT_MODEL))
    print(f"\nSahip ses profili hazır: {DEFAULT_PROFILE}")
    print("Misha'yı yeniden başlat; CLICK TO SPEAK düğmesi etkinleşecek.")


if __name__ == "__main__":
    main()
