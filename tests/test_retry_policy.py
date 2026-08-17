import unittest

from core.retry_policy import classify_retry, exponential_backoff


class RetryPolicyTests(unittest.TestCase):
    def test_typed_and_known_transient_failures_are_retryable(self):
        self.assertTrue(classify_retry(TimeoutError("late")).retryable)
        self.assertTrue(classify_retry("database is locked").retryable)
        self.assertTrue(classify_retry("429 too many requests").retryable)

    def test_permissions_validation_and_unknown_fail_closed(self):
        self.assertFalse(classify_retry("permission denied").retryable)
        self.assertFalse(classify_retry("invalid parameter").retryable)
        self.assertFalse(classify_retry("something odd happened").retryable)

    def test_backoff_is_exponential_and_bounded(self):
        self.assertEqual(
            [exponential_backoff(value) for value in (1, 2, 3, 10)],
            [0.25, 0.5, 1.0, 2.0],
        )


if __name__ == "__main__":
    unittest.main()
