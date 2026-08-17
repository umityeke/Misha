from __future__ import annotations

import unittest

from scripts.run_evals import EXPECTED_COUNTS, ROOT, load_tasks, run


class EvalSuiteTests(unittest.TestCase):
    def test_task_distribution_expected_results_and_verifiers_are_complete(self):
        tasks = load_tasks(ROOT / "evals" / "tasks.json")
        self.assertEqual(len(tasks), sum(EXPECTED_COUNTS.values()))
        for task in tasks:
            self.assertTrue(task.get("goal"))
            self.assertTrue(task.get("verifier"))
            self.assertTrue(task.get("plan") or task.get("steps"))

    def test_all_deterministic_contract_evals_pass_without_live_model_claim(self):
        report = run(load_tasks(ROOT / "evals" / "tasks.json"))
        self.assertEqual(report["passed"], 50)
        self.assertEqual(report["success_rate"], 1.0)
        self.assertFalse(report["live_model_measured"])


if __name__ == "__main__":
    unittest.main()
