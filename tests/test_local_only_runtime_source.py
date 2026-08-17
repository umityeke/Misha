from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from actions import screen_processor


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATHS = (
    ROOT / "main.py",
    ROOT / "ui.py",
    *(ROOT / name for name in ("actions", "agent", "core", "memory", "cloud")),
)
FORBIDDEN_RUNTIME_MARKERS = (
    "google.genai",
    "from google import genai",
    "gemini_api_key",
    "get_gemini_key",
    "gemini-2.",
    "class MishaLive",
    "api_keys.json",
)


def _runtime_python_files():
    for path in RUNTIME_PATHS:
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from path.rglob("*.py")


class LocalOnlyRuntimeSourceTests(unittest.TestCase):
    def test_paid_provider_markers_are_absent_from_runtime_source(self):
        violations = []
        for path in _runtime_python_files():
            source = path.read_text(encoding="utf-8").lower()
            for marker in FORBIDDEN_RUNTIME_MARKERS:
                if marker.lower() in source:
                    violations.append(f"{path.relative_to(ROOT)}: {marker}")
        self.assertEqual(violations, [])

    def test_screen_text_is_analyzed_locally(self):
        player = Mock()
        with (
            patch.object(screen_processor, "_active_window_text", return_value="Editor: test.py"),
            patch.object(screen_processor, "generate_text", return_value="Yerel analiz") as generate,
        ):
            result = screen_processor.screen_process(
                {"angle": "screen", "text": "Ne açık?"}, player=player
            )
        self.assertTrue(result)
        generate.assert_called_once()
        player.write_log.assert_called_once_with("Misha: Yerel analiz")

    def test_camera_fails_closed_without_local_vision(self):
        with patch.object(screen_processor, "generate_text") as generate:
            result = screen_processor.screen_process(
                {"angle": "camera", "text": "Ne görüyorsun?"}
            )
        self.assertFalse(result)
        generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
