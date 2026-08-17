import importlib
import unittest


class CriticalImportSmokeTests(unittest.TestCase):
    def test_runtime_modules_import_without_optional_remote_extra(self):
        modules = (
            "actions.dev_agent",
            "agent.executor",
            "agent.planner",
            "cloud.health_server",
            "core.action_policy",
            "core.ai.runtime",
            "core.voice.barge_in",
            "core.voice.devices",
            "core.voice.identity",
            "core.voice.realtime",
            "core.voice.service",
            "memory.config_manager",
            "memory.learning_store",
            "scripts.doctor",
        )
        for module in modules:
            with self.subTest(module=module):
                self.assertIsNotNone(importlib.import_module(module))


if __name__ == "__main__":
    unittest.main()
