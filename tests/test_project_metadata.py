import tomllib
import unittest
from pathlib import Path


class ProjectMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = tomllib.loads(
            (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]

    def test_project_is_local_first(self):
        dependencies = "\n".join(self.metadata["dependencies"]).lower()
        self.assertNotIn("google-generativeai", dependencies)
        self.assertIn("pynput", dependencies)
        self.assertIn("platform_system != 'darwin'", dependencies)

    def test_remote_database_driver_is_optional(self):
        runtime = "\n".join(self.metadata["dependencies"]).lower()
        remote = "\n".join(self.metadata["optional-dependencies"]["remote"]).lower()
        self.assertNotIn("psycopg2", runtime)
        self.assertIn("psycopg2-binary", remote)


if __name__ == "__main__":
    unittest.main()
