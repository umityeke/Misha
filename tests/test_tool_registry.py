import unittest

from agent.tool_registry import (
    RiskLevel,
    TOOL_REGISTRY,
    get_tool_spec,
    planner_catalog,
    validate_tool_parameters,
)


class ToolRegistryTests(unittest.TestCase):
    def test_every_registered_tool_has_schema_risk_and_timeout(self):
        self.assertGreaterEqual(len(TOOL_REGISTRY), 18)
        for name, spec in TOOL_REGISTRY.items():
            with self.subTest(tool=name):
                self.assertEqual(spec.name, name)
                self.assertIsInstance(spec.risk, RiskLevel)
                self.assertGreater(spec.timeout_seconds, 0)
                self.assertTrue(spec.verifier)
                self.assertIsInstance(spec.approval_required, bool)
                self.assertIsInstance(spec.idempotent, bool)
                self.assertGreaterEqual(spec.max_attempts, 1)
                self.assertTrue(spec.rollback)
                if spec.external_impact:
                    self.assertTrue(spec.approval_required)
                    self.assertFalse(spec.idempotent)
                schema = spec.json_schema()
                self.assertFalse(schema["additionalProperties"])

    def test_unknown_tool_and_unknown_field_fail_closed(self):
        with self.assertRaises(ValueError):
            get_tool_spec("generated_code")
        with self.assertRaises(ValueError):
            validate_tool_parameters(
                "send_message",
                {"receiver": "Ada", "message_text": "Hi", "platform": "x", "token": "no"},
            )

    def test_missing_empty_and_wrong_type_values_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_tool_parameters("respond", {})
        with self.assertRaises(ValueError):
            validate_tool_parameters("respond", {"message": "  "})
        with self.assertRaises(ValueError):
            validate_tool_parameters("computer_control", {"action": "click", "x": "10"})

    def test_valid_parameters_are_copied_not_mutated(self):
        original = {"query": "Misha local agent", "mode": "search"}
        result = validate_tool_parameters("web_search", original)
        self.assertEqual(result, original)
        self.assertIsNot(result, original)

    def test_planner_catalog_is_generated_from_same_registry(self):
        catalog = planner_catalog()
        self.assertEqual(set(catalog), set(TOOL_REGISTRY))
        self.assertFalse(
            catalog["send_message"]["parameters"]["additionalProperties"]
        )
        self.assertTrue(catalog["send_message"]["external_impact"])
        self.assertTrue(catalog["send_message"]["approval_required"])
        self.assertFalse(catalog["send_message"]["idempotent"])
        self.assertEqual(catalog["respond"]["max_attempts"], 3)
        self.assertIn("rollback", catalog["respond"])


if __name__ == "__main__":
    unittest.main()
