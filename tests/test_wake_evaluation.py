import json
import tempfile
import unittest
from pathlib import Path

from core.voice.wake_evaluation import (
    WakeEvaluationSample,
    evaluate_wake_samples,
    load_wake_samples,
    write_wake_manifest,
)


class WakeEvaluationTests(unittest.TestCase):
    def sample(self, **changes):
        values = {
            "sample_id": "sample-1",
            "label": "positive",
            "environment": "silent",
            "speaker_id": "owner",
            "detected": True,
            "duration_seconds": 2.0,
            "latency_ms": 220.0,
        }
        values.update(changes)
        return WakeEvaluationSample(**values)

    def test_report_calculates_environment_and_false_wake_metrics(self):
        samples = [
            *[self.sample(sample_id=f"silent-{index}") for index in range(20)],
            *[
                self.sample(sample_id=f"office-{index}", environment="office")
                for index in range(10)
            ],
            self.sample(
                sample_id="negative-hour",
                label="negative",
                environment="office",
                detected=False,
                duration_seconds=3600,
                latency_ms=None,
            ),
        ]
        report = evaluate_wake_samples(samples)
        self.assertTrue(report["passed"])
        self.assertEqual(report["environments"]["silent"]["success_rate"], 1.0)
        self.assertEqual(report["false_wakes_per_hour"], 0.0)
        self.assertEqual(report["median_detection_latency_ms"], 220.0)

    def test_report_never_passes_without_all_required_measurements(self):
        report = evaluate_wake_samples([self.sample()])
        self.assertFalse(report["thresholds_measured"])
        self.assertFalse(report["passed"])

    def test_manifest_round_trip_and_duplicate_rejection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            write_wake_manifest(path, [self.sample()])
            self.assertEqual(load_wake_samples(path), [self.sample()])
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["samples"].append(payload["samples"][0])
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unique"):
                load_wake_samples(path)

    def test_manifest_rejects_unbounded_or_invalid_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "samples": [
                            {
                                "sample_id": "bad",
                                "label": "positive",
                                "environment": "street",
                                "speaker_id": "owner",
                                "detected": True,
                                "duration_seconds": 2,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "environment"):
                load_wake_samples(path)


if __name__ == "__main__":
    unittest.main()
