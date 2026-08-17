import unittest

from agent.planner import _validate_plan, summarize_plan


class PlannerValidationTests(unittest.TestCase):
    def test_unknown_tool_is_rejected(self):
        plan = {
            "steps": [
                {"tool": "generated_code", "parameters": {}, "description": "unsafe"}
            ]
        }
        with self.assertRaises(ValueError):
            _validate_plan(plan, "test")

    def test_plan_is_limited_and_normalized(self):
        plan = {
            "steps": [
                {"tool": "respond", "parameters": {"message": str(index)}}
                for index in range(8)
            ]
        }
        result = _validate_plan(plan, "chat")
        self.assertEqual(len(result["steps"]), 5)
        self.assertEqual(result["steps"][0]["step"], 1)

    def test_plan_rejects_missing_required_and_unknown_parameters(self):
        for parameters in ({}, {"message": "ok", "unexpected": True}):
            plan = {"steps": [{"tool": "respond", "parameters": parameters}]}
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                _validate_plan(plan, "chat")

    def test_dependencies_are_topologically_ordered_and_canonicalized(self):
        plan = {
            "goal": "research topic",
            "steps": [
                {"step": 20, "tool": "weather_report", "parameters": {"city": "Istanbul"}, "depends_on": [10]},
                {"step": 10, "tool": "web_search", "parameters": {"query": "public weather context"}},
            ],
        }
        result = _validate_plan(plan, "research topic")
        self.assertEqual([step["tool"] for step in result["steps"]], ["web_search", "weather_report"])
        self.assertEqual(result["steps"][1]["depends_on"], [1])

    def test_cycle_self_reference_and_missing_dependency_are_rejected(self):
        invalid_dependencies = (
            ([{"step": 1, "depends_on": [2]}, {"step": 2, "depends_on": [1]}]),
            ([{"step": 1, "depends_on": [1]}]),
            ([{"step": 1, "depends_on": [9]}]),
        )
        for raw_steps in invalid_dependencies:
            steps = [
                {**item, "tool": "respond", "parameters": {"message": str(index)}}
                for index, item in enumerate(raw_steps, start=1)
            ]
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                _validate_plan({"steps": steps}, "chat")

    def test_duplicate_and_already_completed_steps_are_rejected(self):
        duplicate = {
            "steps": [
                {"tool": "web_search", "parameters": {"query": "public news"}},
                {"tool": "web_search", "parameters": {"query": "public news"}},
            ]
        }
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            _validate_plan(duplicate, "public news research")
        completed = [{"tool": "weather_report", "parameters": {"city": "Istanbul"}}]
        with self.assertRaisesRegex(ValueError, "already-completed"):
            _validate_plan(
                {"steps": [{"tool": "weather_report", "parameters": {"city": "Istanbul"}}]},
                "Istanbul weather", completed_steps=completed,
            )

    def test_declared_goal_mismatch_and_local_web_fallback_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not align"):
            _validate_plan(
                {"goal": "send money", "steps": [{"tool": "respond", "parameters": {"message": "ok"}}]},
                "explain Python decorators",
            )
        with self.assertRaisesRegex(ValueError, "local context"):
            _validate_plan(
                {"steps": [{"tool": "web_search", "parameters": {"query": "package.json tests"}}]},
                "inspect this local project",
            )

    def test_respond_cannot_be_hidden_inside_execution_plan(self):
        with self.assertRaisesRegex(ValueError, "cannot be mixed"):
            _validate_plan(
                {"steps": [
                    {"tool": "weather_report", "parameters": {"city": "Istanbul"}},
                    {"tool": "respond", "parameters": {"message": "done"}},
                ]},
                "check Istanbul weather",
            )

    def test_plan_summary_exposes_risk_not_parameters(self):
        plan = _validate_plan(
            {"steps": [{
                "tool": "send_message",
                "description": "Send the approved note",
                "parameters": {"receiver": "Ada", "message_text": "private", "platform": "WhatsApp"},
            }]},
            "send Ada a message",
        )
        summary = summarize_plan(plan)
        self.assertIn("approval required", summary)
        self.assertNotIn("Ada", summary)
        self.assertNotIn("private", summary)


if __name__ == "__main__":
    unittest.main()
