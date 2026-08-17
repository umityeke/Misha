import unittest
from unittest.mock import Mock, patch
from datetime import datetime

from core.proactive import ProactiveAI, ProactiveNotice
from core.proactive_policy import ProactiveSettings


class ProactiveSecurityTests(unittest.TestCase):
    @patch("core.proactive.log_event")
    def test_explicit_consent_is_required(self, log_event):
        service = ProactiveAI()
        self.assertFalse(service.start())
        self.assertFalse(service.running)
        event = log_event.call_args.args[0]
        self.assertEqual(event.status, "rejected")
        self.assertEqual(event.details["reason"], "explicit_consent_required")

    @patch("core.proactive.log_event")
    def test_consent_starts_and_stop_ends_worker(self, _log_event):
        service = ProactiveAI(interval_seconds=5)
        self.assertTrue(service.start(consent=True))
        self.assertTrue(service.running)
        service.stop(timeout=0.5)
        self.assertFalse(service.running)

    @patch("core.memory_service.save_decision")
    @patch("memory.config_manager.record_proactive_notification")
    @patch("memory.config_manager.proactive_budget_available", return_value=True)
    @patch("core.proactive.log_event")
    @patch("core.proactive.current_ide_context.get_context_string")
    def test_context_is_untrusted_and_duplicate_notice_is_suppressed(
        self, get_context, _log_event, _budget, record, _save_decision
    ):
        get_context.return_value = "failing test: AssertionError " * 5
        prompts = []

        def generate(prompt, **_kwargs):
            prompts.append(prompt)
            return {
                "action": "notify",
                "topic": "AssertionError in unit test",
                "rationale": "The test output shows an explicit failure.",
                "decision": "Inspect the failing assertion.",
                "message": "Bir test hatası tespit ettim.",
            }

        observer = Mock(return_value="redacted screen error " * 5)
        callback = Mock()
        service = ProactiveAI(
            observer=observer,
            generator=generate,
            speak_callback=callback,
            denylist=("bank.example",),
            settings=ProactiveSettings.validated(quiet_hours_enabled=False),
        )
        service._analyze_context()
        service._analyze_context()

        observer.assert_called_with(denylist=("bank.example",))
        self.assertIn("UNTRUSTED DATA", prompts[0])
        notice = callback.call_args.args[0]
        self.assertIsInstance(notice, ProactiveNotice)
        self.assertEqual(notice.message, "Bir test hatası tespit ettim.")
        self.assertEqual(notice.priority, "normal")
        record.assert_called_once()

    @patch("core.proactive.log_event")
    @patch("core.proactive.current_ide_context.get_context_string")
    def test_invalid_notification_is_rejected(self, get_context, log_event):
        get_context.return_value = "explicit exception " * 5
        callback = Mock()
        service = ProactiveAI(
            observer=Mock(return_value="traceback " * 10),
            generator=Mock(return_value={"action": "notify", "topic": ""}),
            speak_callback=callback,
            settings=ProactiveSettings.validated(quiet_hours_enabled=False),
        )
        service._analyze_context()
        callback.assert_not_called()
        self.assertEqual(log_event.call_args.args[0].status, "rejected")

    @patch("memory.config_manager.proactive_budget_available", return_value=True)
    @patch("core.proactive.log_event")
    @patch("core.proactive.current_ide_context.get_context_string")
    def test_quiet_hours_suppress_all_priorities(
        self, get_context, log_event, _budget
    ):
        get_context.return_value = "explicit security error " * 5
        callback = Mock()
        service = ProactiveAI(
            observer=Mock(return_value="traceback " * 10),
            generator=Mock(return_value={
                "action": "notify", "priority": "critical", "topic": "risk",
                "message": "Kritik risk.",
            }),
            speak_callback=callback,
            settings=ProactiveSettings.validated(
                quiet_hours_enabled=True, quiet_start="22:00", quiet_end="08:00"
            ),
            now_provider=lambda: datetime(2026, 8, 16, 23, 0),
        )
        service._analyze_context()
        callback.assert_not_called()
        self.assertEqual(log_event.call_args.args[0].details["reason"], "quiet_hours")

    @patch("memory.config_manager.proactive_budget_available", return_value=False)
    @patch("core.proactive.log_event")
    @patch("core.proactive.current_ide_context.get_context_string")
    def test_daily_budget_suppresses_notice(self, get_context, log_event, _budget):
        get_context.return_value = "explicit exception " * 5
        service = ProactiveAI(
            observer=Mock(return_value="traceback " * 10),
            generator=Mock(return_value={
                "action": "notify", "topic": "error", "message": "Hata var."
            }),
            speak_callback=Mock(),
            settings=ProactiveSettings.validated(quiet_hours_enabled=False),
            now_provider=lambda: datetime(2026, 8, 16, 12, 0),
        )
        service._analyze_context()
        self.assertEqual(log_event.call_args.args[0].details["reason"], "daily_limit")


if __name__ == "__main__":
    unittest.main()
