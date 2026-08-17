import os
import plistlib
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from actions import reminder as reminders
from agent.verifier import VerificationStatus, verify_tool_result
from core import reminder_store, reminder_worker


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"MISHA_DATA_DIR": str(self.root / "data"), "TZ": "Europe/Istanbul"})
        self.env.start()
        self.cipher = patch.object(reminder_store, "_CIPHER", Fernet(Fernet.generate_key()))
        self.cipher.start()

    def tearDown(self):
        self.cipher.stop()
        self.env.stop()
        self.temp.cleanup()

    def params(self, **extra):
        value = {
            "action": "create", "date": "2030-06-10", "time": "09:30",
            "message": "private doctor appointment", "timezone": "Europe/Istanbul",
        }
        value.update(extra)
        return value

    def test_timezone_and_dst_validation(self):
        target = reminders._parse_target("2030-06-10", "09:30", "Europe/Istanbul", None)
        self.assertEqual(target.tzinfo.key, "Europe/Istanbul")
        with self.assertRaisesRegex(ValueError, "does not exist"):
            reminders._parse_target("2026-03-29", "02:30", "Europe/Berlin", None)
        with self.assertRaisesRegex(ValueError, "occurs twice"):
            reminders._parse_target("2026-10-25", "02:30", "Europe/Berlin", None)
        first = reminders._parse_target("2026-10-25", "02:30", "Europe/Berlin", 0)
        second = reminders._parse_target("2026-10-25", "02:30", "Europe/Berlin", 1)
        self.assertNotEqual(first.utcoffset(), second.utcoffset())

    def test_create_list_status_delete_and_verifier(self):
        with patch.object(reminders, "_schedule", return_value="scheduler-id"):
            created = reminders.reminder(self.params())
        reminder_id = created.split("Reminder scheduled: ", 1)[1].split()[0]
        self.assertRegex(reminder_id, reminder_store.REMINDER_ID)
        with patch.object(reminders, "scheduler_registered", return_value=True):
            verified = verify_tool_result("reminder", self.params(), created)
        self.assertEqual(verified.status, VerificationStatus.VERIFIED)
        self.assertIn(reminder_id, reminders.reminder({"action": "list"}))
        self.assertIn("scheduled", reminders.reminder({"action": "status", "reminder_id": reminder_id}))
        with patch.object(reminders, "_unschedule", return_value=True):
            deleted = reminders.reminder({"action": "delete", "reminder_id": reminder_id})
        self.assertIn("deleted", deleted)
        deletion = verify_tool_result(
            "reminder", {"action": "delete", "reminder_id": reminder_id}, deleted
        )
        self.assertEqual(deletion.status, VerificationStatus.VERIFIED)

    def test_windows_and_linux_scheduler_verifiers_use_exact_native_ids(self):
        item = {
            "reminder_id": "rem_0000000000000000",
            "scheduler_id": "MishaReminder_rem_0000000000000000",
        }
        completed = subprocess.CompletedProcess([], 0, "Ready", "")
        with patch.object(reminders, "_get_os", return_value="windows"), patch.object(
            reminders.subprocess, "run", return_value=completed
        ) as run:
            self.assertTrue(reminders.scheduler_registered(item))
        self.assertEqual(run.call_args.args[0][:3], ["schtasks", "/Query", "/TN"])

        item["scheduler_id"] = "misha-rem_0000000000000000"
        with patch.object(reminders, "_get_os", return_value="linux"), patch.object(
            reminders.subprocess, "run", return_value=completed
        ) as run:
            self.assertTrue(reminders.scheduler_registered(item))
        self.assertEqual(
            run.call_args.args[0],
            ["systemctl", "--user", "is-active", "misha-rem_0000000000000000.timer"],
        )

    def test_scheduler_verifier_rejects_mismatched_identifier_without_process(self):
        item = {"reminder_id": "rem_0000000000000000", "scheduler_id": "attacker"}
        with patch.object(reminders, "_get_os", return_value="windows"), patch.object(
            reminders.subprocess, "run"
        ) as run:
            self.assertFalse(reminders.scheduler_registered(item))
        run.assert_not_called()

    def test_edit_replaces_old_registration(self):
        with patch.object(reminders, "_schedule", return_value="scheduler-id"):
            created = reminders.reminder(self.params())
            old_id = created.split("Reminder scheduled: ", 1)[1].split()[0]
            with patch.object(reminders, "_unschedule", return_value=True):
                edited = reminders.reminder({
                    "action": "edit", "reminder_id": old_id, "message": "updated",
                })
        self.assertIn("Reminder replaced", edited)
        new_id = edited.split("Reminder scheduled: ", 1)[1].split()[0]
        self.assertNotEqual(old_id, new_id)
        self.assertEqual(reminder_store.get_reminder(old_id)["status"], "deleted")
        self.assertEqual(reminder_store.get_reminder(new_id)["message"], "updated")

    def test_failed_edit_keeps_original_scheduler_record(self):
        with patch.object(reminders, "_schedule", return_value="scheduler-id"):
            created = reminders.reminder(self.params())
        old_id = created.split("Reminder scheduled: ", 1)[1].split()[0]
        with patch.object(reminders, "_schedule", return_value=""):
            edited = reminders.reminder({
                "action": "edit", "reminder_id": old_id, "message": "will fail",
            })
        self.assertIn("original is unchanged", edited)
        self.assertEqual(reminder_store.get_reminder(old_id)["status"], "scheduled")

    def test_message_is_encrypted_at_rest_and_database_is_private(self):
        with patch.object(reminders, "_schedule", return_value="scheduler-id"):
            reminders.reminder(self.params())
        db = reminder_store.data_path()
        raw = db.read_bytes()
        self.assertNotIn(b"private doctor appointment", raw)
        self.assertEqual(db.stat().st_mode & 0o777, 0o600)
        self.assertEqual(db.parent.stat().st_mode & 0o777, 0o700)

    def test_recurring_reminders_require_system_timezone(self):
        result = reminders.reminder(self.params(repeat="daily", timezone="America/New_York"))
        self.assertIn("system timezone", result)

    def test_mac_launch_agent_contains_only_id_and_private_permissions(self):
        target = reminders._parse_target("2030-06-10", "09:30", "Europe/Istanbul", None)
        completed = subprocess.CompletedProcess([], 0, "", "")
        with patch.object(reminders.Path, "home", return_value=self.root), patch.object(
            reminders.subprocess, "run", return_value=completed
        ) as run:
            label = reminders._schedule_mac(target, "rem_0000000000000000", "daily")
        plist_path = self.root / "Library" / "LaunchAgents" / f"{label}.plist"
        with plist_path.open("rb") as handle:
            payload = plistlib.load(handle)
        self.assertIn("--deliver-reminder", payload["ProgramArguments"])
        self.assertNotIn("private", plist_path.read_text(encoding="utf-8"))
        self.assertEqual(plist_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(run.call_args.args[0][0:2], ["launchctl", "bootstrap"])

    def test_worker_marks_one_time_delivered_and_recurring_scheduled(self):
        one = reminder_store.create_reminder_record(
            message="one", local_iso="2030-01-01T10:00:00+03:00",
            utc_iso="2030-01-01T07:00:00+00:00", timezone="Europe/Istanbul",
            fold=0, repeat_rule="none",
        )
        reminder_store.set_scheduled(one, "scheduler")
        with patch.object(reminder_worker, "_notify", return_value=True):
            self.assertEqual(reminder_worker.deliver_reminder(one), 0)
        self.assertEqual(reminder_store.get_reminder(one)["status"], "delivered")

        recurring = reminder_store.create_reminder_record(
            message="daily", local_iso="2030-01-01T10:00:00+03:00",
            utc_iso="2030-01-01T07:00:00+00:00", timezone="Europe/Istanbul",
            fold=0, repeat_rule="daily",
        )
        reminder_store.set_scheduled(recurring, "scheduler")
        with patch.object(reminder_worker, "_notify", return_value=True):
            reminder_worker.deliver_reminder(recurring)
        item = reminder_store.get_reminder(recurring)
        self.assertEqual(item["status"], "scheduled")
        self.assertIsNotNone(item["last_delivered_at"])

    def test_invalid_ids_and_failed_scheduler_are_fail_closed(self):
        self.assertEqual(reminders.reminder({"action": "delete", "reminder_id": "../bad"}), "Invalid reminder ID.")
        with patch.object(reminders, "_schedule", return_value=""):
            result = reminders.reminder(self.params())
        self.assertIn("couldn't register", result)
        with sqlite3.connect(reminder_store.data_path()) as conn:
            status = conn.execute("SELECT status FROM reminders ORDER BY created_at DESC LIMIT 1").fetchone()[0]
        self.assertEqual(status, "failed")


if __name__ == "__main__":
    unittest.main()
