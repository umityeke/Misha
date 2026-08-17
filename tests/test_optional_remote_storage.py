import unittest
from unittest.mock import patch

from core import audit_logger, memory_service


class OptionalRemoteStorageTests(unittest.TestCase):
    def test_memory_service_explains_missing_remote_driver(self):
        with patch.object(memory_service, "psycopg2", None):
            with self.assertRaisesRegex(RuntimeError, "remote extra"):
                memory_service._get_conn()

    def test_audit_logger_explains_missing_remote_driver(self):
        with patch.object(audit_logger, "psycopg2", None):
            with self.assertRaisesRegex(RuntimeError, "remote extra"):
                audit_logger._get_conn()


if __name__ == "__main__":
    unittest.main()
