import tempfile
import unittest
from pathlib import Path

from core.voice.identity import SpeakerVerification
from core.voice.service import LocalVoiceService
from core.voice.stt import VoiceComponentStatus


class _Transcriber:
    def __init__(self, ready=True):
        self.ready = ready

    def status(self):
        return VoiceComponentStatus(self.ready, "stt")

    def transcribe(self, _path):
        return "projeyi test et"


class _Identity:
    def __init__(self, enrolled=True, accepted=True):
        self.enrolled = enrolled
        self.accepted = accepted

    def is_enrolled(self):
        return self.enrolled

    def verify(self, _path):
        return SpeakerVerification(self.accepted, 0.95, "owner" if self.accepted else "denied")


class LocalVoiceServiceTests(unittest.TestCase):
    def test_requires_enrollment(self):
        service = LocalVoiceService(_Transcriber(), _Identity(enrolled=False), lambda _: None)
        self.assertFalse(service.status().ready)

    def test_rejected_speaker_never_reaches_agent(self):
        received = []
        service = LocalVoiceService(
            _Transcriber(), _Identity(accepted=False), received.append
        )
        result = service.process_recording("unused.wav")
        self.assertFalse(result.accepted)
        self.assertEqual(received, [])

    def test_verified_transcript_reaches_agent(self):
        received = []
        service = LocalVoiceService(_Transcriber(), _Identity(), received.append)
        result = service.process_recording("unused.wav")
        self.assertTrue(result.accepted)
        self.assertEqual(result.transcript, "projeyi test et")
        self.assertEqual(received, ["projeyi test et"])

    def test_wake_inspection_does_not_dispatch_before_matching(self):
        received = []
        service = LocalVoiceService(_Transcriber(), _Identity(), received.append)
        result = service.verify_and_transcribe("unused.wav")
        self.assertTrue(result.accepted)
        self.assertEqual(result.transcript, "projeyi test et")
        self.assertEqual(received, [])

    def test_wake_inspection_rejects_non_owner_before_transcription(self):
        received = []
        transcriber = _Transcriber()
        service = LocalVoiceService(
            transcriber,
            _Identity(accepted=False),
            received.append,
        )
        result = service.verify_and_transcribe("unused.wav")
        self.assertFalse(result.accepted)
        self.assertEqual(result.transcript, "")
        self.assertEqual(received, [])


if __name__ == "__main__":
    unittest.main()
