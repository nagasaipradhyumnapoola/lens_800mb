"""Regression evidence: reject corrupt/ambiguous native output before scoring."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from scripts.benchmark_indic_hindi import parse_native_result
except ImportError:
    parse_native_result = None


class IndicNativeOutputTests(unittest.TestCase):
    def parse(self, stdout, stderr=b"", exit_code=0, timed_out=False):
        self.assertIsNotNone(parse_native_result, "Strict native parser is not implemented")
        return parse_native_result(stdout, stderr, exit_code, timed_out)

    def test_preserves_hindi_from_json_surrounded_by_logs(self):
        payload = json.dumps({"text": "हिन्दी नमस्ते", "tokens": []}, ensure_ascii=False).encode()
        self.assertEqual(self.parse(b"diagnostic\n" + payload + b"\n"), "हिन्दी नमस्ते")

    def test_rejects_invalid_utf8_before_json_scoring(self):
        with self.assertRaises(UnicodeDecodeError):
            self.parse(b'{"text":"\xff"}')

    def test_rejects_json_escaped_lone_surrogate(self):
        with self.assertRaises(UnicodeEncodeError):
            self.parse(b'{"text":"\\ud800"}')

    def test_rejects_nonzero_exit_even_with_plausible_text(self):
        with self.assertRaises(RuntimeError):
            self.parse(b'{"text":"valid"}', exit_code=1)

    def test_rejects_timeout_even_with_plausible_text(self):
        with self.assertRaises(RuntimeError):
            self.parse(b'{"text":"valid"}', timed_out=True)

    def test_rejects_ambiguous_transcripts(self):
        with self.assertRaises(ValueError):
            self.parse(b'{"text":"one"}\n{"text":"two"}')

    def test_rejects_missing_transcript(self):
        with self.assertRaises(ValueError):
            self.parse(b"diagnostics only")


if __name__ == "__main__":
    unittest.main()
