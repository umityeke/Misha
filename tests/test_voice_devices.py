import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from core.voice.devices import AudioDeviceError, AudioDeviceManager
from core.voice.recorder import SoundDeviceRecorder


class _Default:
    device = (1, 2)


class FakeAudioBackend:
    default = _Default()

    def __init__(self):
        self.devices = [
            {
                "name": "Old microphone",
                "max_input_channels": 1,
                "max_output_channels": 0,
                "default_samplerate": 44100,
            },
            {
                "name": "MacBook Microphone",
                "max_input_channels": 2,
                "max_output_channels": 0,
                "default_samplerate": 48000,
            },
            {
                "name": "MacBook Speakers",
                "max_input_channels": 0,
                "max_output_channels": 2,
                "default_samplerate": 48000,
            },
        ]
        self.unsupported_inputs = {0}

    def query_devices(self):
        return self.devices

    def check_input_settings(self, *, device, **_kwargs):
        if device in self.unsupported_inputs:
            raise ValueError("unsupported")

    def check_output_settings(self, *, device, **_kwargs):
        if device != 2:
            raise ValueError("unsupported")


class AudioDeviceManagerTests(unittest.TestCase):
    def test_lists_input_and_output_devices_separately(self):
        manager = AudioDeviceManager(FakeAudioBackend())
        self.assertEqual([d.index for d in manager.list_devices("input")], [0, 1])
        self.assertEqual([d.index for d in manager.list_devices("output")], [2])

    def test_falls_back_from_unsupported_preference_to_default(self):
        manager = AudioDeviceManager(FakeAudioBackend())
        selected = manager.resolve_input(preferred_index=0)
        self.assertEqual(selected.index, 1)
        self.assertTrue(selected.is_default_input)

    def test_name_survives_changed_device_index(self):
        backend = FakeAudioBackend()
        backend.default.device = (-1, 2)
        manager = AudioDeviceManager(backend)
        selected = manager.resolve_input(
            preferred_index=99,
            preferred_name="MacBook Microphone",
        )
        self.assertEqual(selected.index, 1)

    def test_disconnect_of_preferred_device_recovers_to_new_default(self):
        backend = FakeAudioBackend()
        manager = AudioDeviceManager(backend)
        self.assertEqual(manager.resolve_input(preferred_name="MacBook Microphone").index, 1)
        backend.devices[1] = {
            "name": "USB fallback microphone",
            "max_input_channels": 1,
            "max_output_channels": 0,
            "default_samplerate": 48000,
        }
        backend.default.device = (1, 2)
        recovered = manager.resolve_input(preferred_name="MacBook Microphone")
        self.assertEqual(recovered.name, "USB fallback microphone")
        self.assertTrue(recovered.is_default_input)

    def test_missing_input_fails_with_clear_error(self):
        backend = FakeAudioBackend()
        backend.devices = [backend.devices[2]]
        manager = AudioDeviceManager(backend)
        with self.assertRaisesRegex(AudioDeviceError, "No local input"):
            manager.resolve_input()

    def test_recorder_uses_resolved_device_index(self):
        manager = AudioDeviceManager(FakeAudioBackend())
        recorder = SoundDeviceRecorder(
            device_manager=manager,
            preferred_input_name="MacBook Microphone",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "sample.wav"
            with (
                patch(
                    "sounddevice.rec",
                    return_value=np.zeros((16000, 1), dtype=np.float32),
                ) as record,
                patch("sounddevice.wait"),
            ):
                recorder.record(destination, seconds=1)
            self.assertEqual(record.call_args.kwargs["device"], 1)
            self.assertTrue(destination.is_file())


if __name__ == "__main__":
    unittest.main()
