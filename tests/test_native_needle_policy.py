"""Black-box checks for Lens's boundary around an untrusted native proposal.

Real English/negation cases use the pinned DLL. A tiny temporary DLL substitutes
only the external model for impossible-to-force malformed proposals; the actual
lens-needle executable, schema checks and policy run unchanged. No actions run.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "build/engine/Release/lens-needle.exe"
TOOLS = json.loads((ROOT / "data/fixtures/extraction-tools.json").read_text(encoding="utf-8"))
ENGLISH = "I have a meeting with Arun in Chennai on 2026-10-27 at 15:00."
ARGUMENTS = {"person": "Arun", "date": "2026-10-27", "time": "15:00", "place": "Chennai"}


class NativeNeedlePolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not EXE.exists():
            raise RuntimeError("Build the lens-needle target before running this test")
        cls.temp = tempfile.TemporaryDirectory(prefix="lens-needle-policy-")
        cls.work = Path(cls.temp.name)
        cls.addClassCleanup(cls.temp.cleanup)
        cls.weights = cls.work / "synthetic.cact"
        cls.weights.write_bytes(b"synthetic test stub, not model weights")
        source = cls.work / "model_stub.cpp"
        source.write_text(r'''
#include <cstdlib>
#include <cstring>
extern "C" __declspec(dllexport) int needle_load(const unsigned char*, unsigned long long) { return 0; }
extern "C" __declspec(dllexport) int needle_init(const char*, const char*, const char*) { return 64; }
extern "C" __declspec(dllexport) int needle_complete(const char*, const float*, int, int, char* out, int n) {
    const char* value = std::getenv("LENS_POLICY_TEST_RESPONSE");
    if (!value || std::strlen(value) + 1 > static_cast<unsigned>(n)) return -1;
    std::memcpy(out, value, std::strlen(value) + 1);
    return 1;
}
''', encoding="utf-8")
        vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
        install = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-property", "installationPath"], text=True).strip()
        vcvars = Path(install) / "VC/Auxiliary/Build/vcvars64.bat"
        cls.dll = cls.work / "model_stub.dll"
        command = f'call "{vcvars}" >nul && cl /nologo /LD /EHsc /std:c++20 "{source}" /Fe:"{cls.dll}"'
        build = subprocess.run(command, shell=True, cwd=cls.work, text=True, capture_output=True)
        if build.returncode:
            raise RuntimeError("Temporary model-boundary stub build failed: " + build.stdout + build.stderr)

    def request(self, *, tools=None, proposal=None, text=ENGLISH):
        request = {"library": str(ROOT / "models/Cactus-Compute--needle3/windows-x86_64/libneedle3.dll"),
                   "weights": str(ROOT / "models/Cactus-Compute--needle3/needle3.cact"),
                   "tools": copy.deepcopy(TOOLS if tools is None else tools), "text": text}
        env = os.environ.copy()
        if proposal is not None:
            request.update(library=str(self.dll), weights=str(self.weights))
            env["LENS_POLICY_TEST_RESPONSE"] = json.dumps(proposal, ensure_ascii=True)
        return subprocess.run([str(EXE)], input=json.dumps(request, ensure_ascii=False) + "\n",
                              encoding="utf-8", capture_output=True, timeout=30, env=env, cwd=ROOT)

    @staticmethod
    def envelope(arguments=None, name="save_event"):
        return {"type": "call", "success": True, "error": None, "error_code": None,
                "function_calls": [{"name": name, "arguments": ARGUMENTS if arguments is None else arguments}],
                "suppressed_calls": [], "reasoning": "Synthetic boundary fixture", "confidence": 0.9,
                "validation": {"ungrounded": [], "negation": False}}

    def assert_blocked(self, proposal, *, tools=None):
        proc = self.request(proposal=proposal, tools=tools)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result.get("function_calls"), [], "Unsafe native proposals must not remain callable")
        self.assertEqual(result.get("accepted_calls"), [], "Unsafe proposals must not become accepted records")
        self.assertTrue(result.get("blocked_calls"), "A refusal must have a diagnostic reason")
        self.assertTrue(all(row.get("reason") for row in result["blocked_calls"]))
        self.assertEqual(result.get("proposal"), proposal, "Preserve raw proposal separately from policy acceptance")

    def test_real_negated_meeting_is_blocked_even_if_native_emits_call(self):
        proc = self.request(text="I do not have a meeting with Arun in Chennai on 2026-10-27 at 15:00.")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result.get("function_calls"), [], "A native negation flag must prevent acceptance")
        self.assertEqual(result.get("accepted_calls"), [])
        self.assertTrue(result.get("blocked_calls"))
        self.assertTrue(result.get("proposal", {}).get("validation", {}).get("negation"))

    def test_real_positive_english_remains_compatible(self):
        proc = self.request()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["function_calls"], [{"name": "save_event", "arguments": ARGUMENTS}])
        self.assertEqual(result.get("accepted_calls"), result["function_calls"])
        self.assertEqual(result.get("blocked_calls"), [])

    def test_unknown_native_function_cannot_be_accepted(self):
        self.assert_blocked(self.envelope(name="delete_everything"))

    def test_native_negation_and_uncertainty_flags_are_blocked(self):
        for flag in ("negation", "uncertain", "uncertainty", "needs_confirmation", "requires_confirmation"):
            with self.subTest(flag=flag):
                proposal = self.envelope()
                proposal["validation"][flag] = True
                self.assert_blocked(proposal)

    def test_top_level_uncertainty_is_blocked(self):
        proposal = self.envelope()
        proposal["uncertain"] = True
        self.assert_blocked(proposal)

    def test_ungrounded_fields_are_blocked(self):
        proposal = self.envelope()
        proposal["validation"]["ungrounded"] = ["save_event.person"]
        self.assert_blocked(proposal)

    def test_missing_required_field_is_blocked(self):
        arguments = dict(ARGUMENTS)
        del arguments["person"]
        self.assert_blocked(self.envelope(arguments))

    def test_wrong_field_types_are_blocked(self):
        for invalid in (42, None, False, ["Arun"], {"value": "Arun"}):
            with self.subTest(invalid=invalid):
                self.assert_blocked(self.envelope({**ARGUMENTS, "person": invalid}))

    def test_extra_arguments_are_blocked(self):
        self.assert_blocked(self.envelope({**ARGUMENTS, "password": "synthetic-marker"}))

    def test_suppressed_call_is_never_promoted(self):
        proposal = self.envelope()
        proposal["suppressed_calls"] = proposal["function_calls"]
        proposal["function_calls"] = []
        proposal["confidence"] = 0.03
        self.assert_blocked(proposal)

    def test_invalid_or_missing_confidence_is_blocked(self):
        for value in (None, -0.1, 1.1, "0.9", 0.02, True):
            with self.subTest(value=value):
                proposal = self.envelope()
                proposal["confidence"] = value
                self.assert_blocked(proposal)
        proposal = self.envelope()
        del proposal["confidence"]
        self.assert_blocked(proposal)

    def test_malformed_validation_cannot_bypass_gate(self):
        for value in ([], "safe", {"negation": "false"}, {"ungrounded": False}, {"new_safety_flag": True}):
            with self.subTest(validation=value):
                proposal = self.envelope()
                proposal["validation"] = value
                self.assert_blocked(proposal)

    def test_unregistered_tool_schema_is_rejected(self):
        tools = copy.deepcopy(TOOLS)
        tools[0]["function"]["name"] = "delete_everything"
        proc = self.request(tools=tools, proposal=self.envelope())
        self.assertNotEqual(proc.returncode, 0, "Only the explicitly allowlisted extraction tool is supported")
        self.assertIn("tool", proc.stderr)

    def test_unsupported_schema_keywords_are_rejected(self):
        for keyword, value in (("pattern", ".*"), ("format", "date"), ("oneOf", [{"type": "string"}]), ("$ref", "#/x")):
            with self.subTest(keyword=keyword):
                tools = copy.deepcopy(TOOLS)
                tools[0]["function"]["parameters"]["properties"]["date"][keyword] = value
                proc = self.request(tools=tools, proposal=self.envelope())
                self.assertNotEqual(proc.returncode, 0, "Unsupported schema features must fail closed")
                self.assertIn("schema", proc.stderr)

    def test_invalid_schema_type_and_required_names_are_rejected(self):
        for change in ("type", "required", "additionalProperties"):
            with self.subTest(change=change):
                tools = copy.deepcopy(TOOLS)
                parameters = tools[0]["function"]["parameters"]
                if change == "type":
                    parameters["properties"]["person"]["type"] = "mystery"
                elif change == "required":
                    parameters["required"] = ["unlisted"]
                else:
                    parameters["additionalProperties"] = True
                proc = self.request(tools=tools, proposal=self.envelope())
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("schema", proc.stderr)

    def test_flat_official_schema_and_empty_refusal_work(self):
        proposal = self.envelope()
        tools = [copy.deepcopy(TOOLS[0]["function"])]
        proc = self.request(tools=tools, proposal=proposal)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result.get("accepted_calls"), [{"name": "save_event", "arguments": ARGUMENTS}])
        proposal["function_calls"] = []
        proc = self.request(tools=tools, proposal=proposal)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result.get("accepted_calls"), [])
        self.assertEqual(result.get("blocked_calls"), [])

    def test_supported_scalar_and_nested_types_are_checked(self):
        cases = [
            ({"type": "integer"}, 7, 7.5),
            ({"type": "number"}, 7.5, "7.5"),
            ({"type": "boolean"}, True, 1),
            ({"type": "null"}, None, "null"),
            ({"type": "array", "items": {"type": "integer"}}, [1, 2], [1, "2"]),
            ({"type": "object", "properties": {"enabled": {"type": "boolean"}}, "required": ["enabled"]},
             {"enabled": True}, {"enabled": True, "extra": 1}),
        ]
        for schema, valid, invalid in cases:
            with self.subTest(schema=schema):
                tools = [{"name": "save_event", "parameters": {"type": "object",
                         "properties": {"value": schema}, "required": ["value"]}}]
                good = self.envelope({"value": valid})
                proc = self.request(tools=tools, proposal=good)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(json.loads(proc.stdout).get("accepted_calls"), good["function_calls"])
                self.assert_blocked(self.envelope({"value": invalid}), tools=tools)

    def test_failed_and_malformed_native_envelopes_are_blocked(self):
        for change, value in (("success", False), ("type", "unexpected"),
                              ("function_calls", {"name": "save_event"}),
                              ("suppressed_calls", "invalid")):
            with self.subTest(change=change):
                proposal = self.envelope()
                proposal[change] = value
                self.assert_blocked(proposal)

    def test_native_error_fields_cannot_be_overridden_by_success_true(self):
        for field in ("error", "error_code"):
            with self.subTest(field=field):
                proposal = self.envelope()
                proposal[field] = "synthetic_native_failure"
                self.assert_blocked(proposal)

    def test_call_metadata_cannot_smuggle_an_extra_operation(self):
        proposal = self.envelope()
        proposal["function_calls"][0]["execute"] = "delete"
        self.assert_blocked(proposal)


if __name__ == "__main__":
    unittest.main(verbosity=2)
