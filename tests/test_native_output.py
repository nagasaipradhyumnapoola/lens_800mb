import json
from pathlib import Path
import tempfile
import unittest

try:
    from scripts.benchmark import parse_native_asr
except ImportError:
    parse_native_asr = None


class NativeOutputTests(unittest.TestCase):
    def test_reads_cli_appended_extension_and_preserves_script(self):
        self.assertIsNotNone(parse_native_asr, "Native JSON parser does not exist")
        with tempfile.TemporaryDirectory() as folder:
            stem = Path(folder) / "sample.wav"
            Path(str(stem) + ".json").write_text(json.dumps({"result": {"language": "ta"},
                "transcription": [{"text": " தமிழ்"}, {"text": " உரை"}]}), encoding="utf-8")
            self.assertEqual(parse_native_asr(stem), ("தமிழ் உரை", "ta"))


if __name__ == "__main__":
    unittest.main()
