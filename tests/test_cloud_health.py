import unittest

from cloud.health_server import health_payload


class CloudHealthTests(unittest.TestCase):
    def test_health_endpoint(self):
        payload = health_payload()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["intelligence"], "local-only")


if __name__ == "__main__":
    unittest.main()
