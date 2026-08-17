import unittest
from unittest.mock import patch

from actions import computer_settings
from agent.verifier import VerificationStatus, verify_tool_result


class SystemSettingsVerifierTests(unittest.TestCase):
    def test_mute_and_unmute_are_exact_on_macos(self):
        with patch.object(computer_settings, "_OS", "Darwin"), patch.object(
            computer_settings.subprocess, "run"
        ) as run:
            computer_settings.volume_mute(True)
            computer_settings.volume_unmute()

        self.assertIn("set volume output muted true", run.call_args_list[0].args[0])
        self.assertIn("set volume output muted false", run.call_args_list[1].args[0])
        self.assertTrue(all(call.kwargs["check"] for call in run.call_args_list))

    def test_audio_setting_verifier_confirms_target_state(self):
        with patch(
            "actions.computer_settings.read_audio_state",
            return_value={"volume": 41, "muted": False},
        ):
            volume = verify_tool_result(
                "computer_settings", {"action": "volume_set", "value": 40}, "Volume set to 40%."
            )
            unmute = verify_tool_result(
                "computer_settings", {"action": "unmute"}, "Done: unmute."
            )

        self.assertIs(volume.status, VerificationStatus.VERIFIED)
        self.assertIs(unmute.status, VerificationStatus.VERIFIED)

    def test_audio_setting_verifier_fails_closed_and_other_actions_stay_unverified(self):
        with patch(
            "actions.computer_settings.read_audio_state",
            return_value={"volume": 90, "muted": True},
        ):
            mismatch = verify_tool_result(
                "computer_settings", {"action": "volume_set", "value": 20}, "Volume set to 20%."
            )
        unsupported = verify_tool_result(
            "computer_settings", {"action": "brightness_up"}, "Done: brightness_up."
        )

        self.assertIs(mismatch.status, VerificationStatus.FAILED)
        self.assertIs(unsupported.status, VerificationStatus.UNVERIFIED)


if __name__ == "__main__":
    unittest.main()
