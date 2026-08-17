import unittest

from core.voice.state import VoiceSessionState, VoiceStateMachine


class VoiceStateMachineTests(unittest.TestCase):
    def test_happy_path_reaches_listening(self):
        machine = VoiceStateMachine()
        machine.transition(VoiceSessionState.WAKE_DETECTED)
        machine.transition(VoiceSessionState.VERIFYING_SPEAKER)
        machine.transition(VoiceSessionState.LISTENING)
        self.assertEqual(machine.state, VoiceSessionState.LISTENING)
        self.assertEqual(len(machine.history), 3)

    def test_invalid_transition_is_rejected(self):
        machine = VoiceStateMachine()
        with self.assertRaises(ValueError):
            machine.transition(VoiceSessionState.EXECUTING)

    def test_error_and_cancel_fail_safe_from_active_state(self):
        machine = VoiceStateMachine()
        machine.transition(VoiceSessionState.WAKE_DETECTED)
        machine.transition(VoiceSessionState.CANCELLED, "user interrupted")
        self.assertEqual(machine.state, VoiceSessionState.CANCELLED)
        machine.transition(VoiceSessionState.IDLE)
        self.assertEqual(machine.state, VoiceSessionState.IDLE)

    def test_execution_can_verify_recover_and_resume(self):
        machine = VoiceStateMachine()
        machine.transition(VoiceSessionState.WAKE_DETECTED)
        machine.transition(VoiceSessionState.VERIFYING_SPEAKER)
        machine.transition(VoiceSessionState.LISTENING)
        machine.transition(VoiceSessionState.UNDERSTANDING)
        machine.transition(VoiceSessionState.PLANNING)
        machine.transition(VoiceSessionState.EXECUTING)
        machine.transition(VoiceSessionState.VERIFYING)
        machine.transition(VoiceSessionState.RECOVERING)
        machine.transition(VoiceSessionState.EXECUTING)
        machine.transition(VoiceSessionState.RESPONDING)
        self.assertEqual(machine.state, VoiceSessionState.RESPONDING)


if __name__ == "__main__":
    unittest.main()
