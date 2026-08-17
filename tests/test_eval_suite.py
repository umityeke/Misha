from __future__ import annotations

import unittest

from scripts.run_evals import EXPECTED_COUNTS, ROOT, load_tasks, run, run_live


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

    def test_live_eval_measures_model_output_without_executing_tools(self):
        tasks = load_tasks(ROOT / "evals" / "tasks.json")[:2]

        def generator(prompt):
            task = next(task for task in tasks if f"Goal: {task['goal']}" in prompt)
            return {
                "goal": task["goal"],
                "steps": [{
                    "step": 1, "tool": task["plan"]["tool"],
                    "description": "fixture", "parameters": task["plan"]["parameters"],
                    "critical": False, "depends_on": [],
                }],
            }

        report = run_live(tasks, generator)
        self.assertTrue(report["live_model_measured"])
        self.assertEqual(report["passed"], 2)
        self.assertEqual(report["success_rate"], 1.0)

    def test_live_security_eval_accepts_only_rejection_or_safe_response(self):
        task = load_tasks(ROOT / "evals" / "tasks.json")[-1]
        safe = run_live([task], lambda _prompt: {
            "goal": task["goal"],
            "steps": [{
                "step": 1, "tool": "respond", "description": "refuse safely",
                "parameters": {"message": "Unsupported mixed execution plan."},
                "critical": False, "depends_on": [],
            }],
        })
        unsafe = run_live([task], lambda _prompt: {
            "goal": task["goal"],
            "steps": [{
                "step": 1, "tool": "weather_report", "description": "execute",
                "parameters": {"city": "Istanbul"}, "critical": False, "depends_on": [],
            }],
        })
        self.assertEqual(safe["passed"], 1)
        self.assertEqual(unsafe["passed"], 0)
        self.assertEqual(unsafe["results"][0]["proposed_tools"], ["weather_report"])


if __name__ == "__main__":
    unittest.main()
