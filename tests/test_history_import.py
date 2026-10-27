"""Real PowerShell/native import contract, using generated synthetic exports only."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from support import pwsh

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/import-history.ps1"
ENGINE = ROOT / "build/engine/Release/lens-engine.exe"


class HistoryImport(unittest.TestCase):
    def invoke(self, source, db, fmt="WhatsApp", *options):
        self.assertTrue(SCRIPT.exists(), "History import adapter is not implemented")
        return subprocess.run(
            [pwsh(), "-NoProfile", "-File", str(SCRIPT), "-Format", fmt,
             "-SourcePath", str(source), "-DatabasePath", str(db), *options],
            capture_output=True, encoding="utf-8", timeout=60)

    def successful(self, *args):
        p = self.invoke(*args)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(p.stderr, "")
        result = json.loads(p.stdout)
        self.assertTrue(result["ok"])
        self.assertTrue(result["atomic"])
        self.assertFalse(result["partial"])
        return result

    def rejected(self, *args):
        p = self.invoke(*args)
        self.assertNotEqual(p.returncode, 0)
        result = json.loads(p.stdout)
        self.assertFalse(result["ok"])
        self.assertTrue(result["atomic"])
        self.assertFalse(result["partial"])
        self.assertEqual(result["imported"], 0)
        return p

    def native(self, db, request):
        p = subprocess.run([str(ENGINE), "--db", str(db)],
                           input=json.dumps(request, ensure_ascii=False) + "\n",
                           capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        result = json.loads(p.stdout)
        self.assertTrue(result["ok"], result)
        return result

    def sources(self, db, query):
        return self.native(db, {"op": "search", "query": query})["sources"]

    def write(self, folder, text, name="synthetic-export.txt"):
        path = Path(folder) / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def jsonl_record(self, **updates):
        return {"id": "original-synthetic-id", "text": "Synthetic JSON history anchor",
                "language": "en", "timestamp": "2018-05-04T11:12:13+05:30",
                "original_timestamp": "2018-05-04T11:12:13+05:30",
                "observed_at": "2020-01-02T03:04:05Z", "timezone": "UTC+05:30",
                "device": "synthetic-export-device", "kind": "imported_note",
                "source_application": "SyntheticNotes", "source_locator": "synthetic:note-7",
                "provenance": "synthetic fixture provenance",
                "consent_context": {"mode": "synthetic_original_authorization"},
                "metadata": {"sender": "Synthetic Person"}, **updates}

    def jsonl(self, folder, records, version=1):
        lines = [json.dumps({"format": "lens-history", "version": version})]
        lines.extend(json.dumps(x, ensure_ascii=False) for x in records)
        return self.write(folder, "\n".join(lines) + "\n", "synthetic-export.jsonl")

    def test_android_old_time_multiline_unicode_and_repeat_dedup(self):
        # Losing the source clock, CRLF continuation, Unicode or stable identity breaks this.
        with tempfile.TemporaryDirectory() as tmp:
            body = "31/12/2020, 23:58 - Alice: 北京 syntheticanchor\r\n第二行 café\r\n01/01/2021, 00:01 - Bob: Another synthetic message\r\n"
            source = self.write(tmp, body)
            db = Path(tmp) / "memory.db"
            options = ("-DateOrder", "DMY", "-SourceTimeZone", "UTC+05:30")
            first = self.successful(source, db, "WhatsApp", *options)
            self.assertEqual(first["imported"], 2)
            self.assertEqual(source.read_bytes(), body.encode("utf-8"))
            row = self.sources(db, "syntheticanchor")[0]
            self.assertEqual(row["text"], "北京 syntheticanchor\r\n第二行 café")
            self.assertEqual(row["timestamp"], "2020-12-31T23:58:00+05:30")
            self.assertEqual(row["original_timestamp"], "2020-12-31T23:58:00+05:30")
            self.assertNotEqual(row["observed_at"], row["timestamp"])
            self.assertEqual(row["timezone"], "UTC+05:30")
            self.assertEqual(row["source_application"], "WhatsApp")
            self.assertEqual(row["metadata"]["sender"], "Alice")
            self.assertEqual(row["consent_context"]["mode"], "user_selected_export")
            self.assertIn(hashlib.sha256(body.encode("utf-8")).hexdigest(), row["provenance"])
            again = self.successful(source, db, "WhatsApp", *options)
            self.assertEqual((again["imported"], again["deduplicated"]), (0, 2))
            self.assertEqual(self.native(db, {"op": "stats"})["source_count"], 2)
            self.assertEqual(self.sources(db, "syntheticanchor")[0]["id"], row["id"])

    def test_ios_two_digit_year_requires_explicit_century(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.write(tmp, "\u200e[12/31/20, 11:58:59 PM] Ana: café iosanchor\ncontinued 中文\n")
            db = Path(tmp) / "memory.db"
            options = ("-DateOrder", "MDY", "-SourceTimeZone", "UTC")
            self.rejected(source, db, "WhatsApp", *options)
            self.successful(source, db, "WhatsApp", *options, "-TwoDigitYearCentury", "2000")
            row = self.sources(db, "iosanchor")[0]
            self.assertEqual(row["text"], "café iosanchor\ncontinued 中文")
            self.assertEqual(row["timestamp"], "2020-12-31T23:58:59+00:00")

    def test_ambiguous_date_requires_order_and_obeys_each_explicit_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.write(tmp, "01/02/2020, 15:04 - Alice: dateanchor\n")
            self.rejected(source, Path(tmp)/"missing.db", "WhatsApp", "-SourceTimeZone", "UTC")
            for order, expected in (("DMY", "2020-02-01T15:04:00+00:00"),
                                    ("MDY", "2020-01-02T15:04:00+00:00")):
                db = Path(tmp) / (order + ".db")
                self.successful(source, db, "WhatsApp", "-DateOrder", order, "-SourceTimeZone", "UTC")
                self.assertEqual(self.sources(db, "dateanchor")[0]["timestamp"], expected)

    def test_dst_invalid_and_ambiguous_wall_times_reject_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/"memory.db"
            for date in ("03/10/2024, 02:30", "11/03/2024, 01:30"):
                source = self.write(tmp, date + " - Alice: DST syntheticanchor\n")
                self.rejected(source, db, "WhatsApp", "-DateOrder", "MDY", "-SourceTimeZone", "America/New_York")
            self.assertEqual(self.native(db, {"op": "stats"})["source_count"], 0)

    def test_late_malformed_date_and_unknown_export_header_reject_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/"memory.db"
            for body in ("31/12/2020, 12:00 - Alice: validanchor\n32/12/2020, 12:01 - Bob: bad\n",
                         "Unrecognized export preface\n31/12/2020, 12:00 - Alice: validanchor\n"):
                source = self.write(tmp, body)
                self.rejected(source, db, "WhatsApp", "-DateOrder", "DMY", "-SourceTimeZone", "UTC")
            self.assertEqual(self.native(db, {"op": "stats"})["source_count"], 0)

    def test_native_sensitive_record_rolls_back_prior_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.write(tmp, "31/12/2020, 12:00 - Alice: allowedanchor\n31/12/2020, 12:01 - Bob: password: synthetic-value\n")
            db = Path(tmp)/"memory.db"
            rejected = self.rejected(source, db, "WhatsApp", "-DateOrder", "DMY", "-SourceTimeZone", "UTC")
            self.assertEqual(json.loads(rejected.stdout)["outcome"], "rolled_back")
            self.assertEqual(self.native(db, {"op": "stats"})["source_count"], 0)

    def test_versioned_jsonl_retains_source_metadata_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.jsonl(tmp, [self.jsonl_record()])
            db = Path(tmp)/"memory.db"
            self.assertEqual(self.successful(source, db, "LensJsonl")["imported"], 1)
            row = self.sources(db, "history anchor")[0]
            self.assertEqual(row["original_timestamp"], "2018-05-04T11:12:13+05:30")
            self.assertEqual(row["source_application"], "SyntheticNotes")
            self.assertEqual(row["metadata"]["sender"], "Synthetic Person")
            self.assertEqual(row["metadata"]["source_record_id"], "original-synthetic-id")
            self.assertEqual(row["metadata"]["source_observed_at"], "2020-01-02T03:04:05Z")
            self.assertEqual(row["consent_context"]["source_context"]["mode"], "synthetic_original_authorization")
            self.assertEqual(self.successful(source, db, "LensJsonl")["deduplicated"], 1)

    def test_jsonl_invalid_version_fields_or_conflicting_times_leave_no_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/"memory.db"
            source = self.jsonl(tmp, [self.jsonl_record()], version=99)
            self.rejected(source, db, "LensJsonl")
            invalids = [self.jsonl_record(timestamp="not-a-timestamp"),
                        self.jsonl_record(original_timestamp="2019-05-04T11:12:13+05:30"),
                        self.jsonl_record(timezone=""), self.jsonl_record(text=None),
                        self.jsonl_record(consent_context={}), self.jsonl_record(unknown_field="must not disappear")]
            for record in invalids:
                source = self.jsonl(tmp, [self.jsonl_record(), record])
                self.rejected(source, db, "LensJsonl")
            source = self.jsonl(tmp, [self.jsonl_record()])
            with source.open("a", encoding="utf-8") as file:
                file.write("{ malformed json\n")
            self.rejected(source, db, "LensJsonl")
            self.assertEqual(self.native(db, {"op": "stats"})["source_count"], 0)

    def test_selected_markdown_preserves_exact_text_and_requires_explicit_original_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = "# Old synthetic note\r\n\r\n北京 markdownanchor café\r\n"
            source = self.write(tmp, body, "synthetic-note.md")
            db = Path(tmp)/"memory.db"
            self.rejected(source, db, "Text")
            options = ("-OriginalTimestamp", "2017-02-03T04:05:06Z", "-SourceApplication", "SyntheticEditor")
            self.assertEqual(self.successful(source, db, "Text", *options)["imported"], 1)
            row = self.sources(db, "markdownanchor")[0]
            self.assertEqual(row["text"], body)
            self.assertEqual(row["original_timestamp"], "2017-02-03T04:05:06Z")
            self.assertEqual(row["source_application"], "SyntheticEditor")
            self.assertEqual(self.successful(source, db, "Text", *options)["deduplicated"], 1)

    def test_jsonl_rejects_duplicate_keys_comments_and_trailing_commas(self):
        # A permissive JSON decoder must not silently discard duplicate source fields.
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/"memory.db"
            valid = json.dumps(self.jsonl_record())
            invalids = ['{"text":"discarded synthetic text",' + valid[1:],
                        valid[:-1] + ',}', '/* synthetic comment */' + valid]
            for row in invalids:
                source = self.write(tmp, '{"format":"lens-history","version":1}\n' + row + '\n', "synthetic-export.jsonl")
                self.rejected(source, db, "LensJsonl")
            self.assertEqual(self.native(db, {"op": "stats"})["source_count"], 0)

    def test_file_record_and_native_wire_limits_reject_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/"memory.db"
            options = ("-OriginalTimestamp", "2017-02-03T04:05:06Z")
            for size in (1024*1024+1, 16*1024*1024+1):
                source = self.write(tmp, "x"*size)
                self.rejected(source, db, "Text", *options)
            # The former 128-record cap is replaced by chunked import (tests/test_unicode_privacy.py);
            # an oversized record after a valid one still rejects before any write.
            source = self.jsonl(tmp, [self.jsonl_record(id="0", text="ok"), self.jsonl_record(id="1", text="x"*(1024*1024+1))])
            self.rejected(source, db, "LensJsonl")
            self.assertEqual(self.native(db, {"op": "stats"})["source_count"], 0)

    def test_utf8_is_strict_and_diagnostics_do_not_echo_selected_paths_or_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/"PRIVATE_PATH_SENTINEL.txt"
            source.write_bytes(b"PRIVATE_CONTENT_SENTINEL\xff\xfe")
            db = Path(tmp)/"memory.db"
            for selected in (source, Path(tmp)/"PRIVATE_PATH_SENTINEL_MISSING.txt"):
                p = self.rejected(selected, db, "Text", "-OriginalTimestamp", "2017-02-03T04:05:06Z")
                self.assertNotIn("PRIVATE_PATH_SENTINEL", p.stdout+p.stderr)
                self.assertNotIn("PRIVATE_CONTENT_SENTINEL", p.stdout+p.stderr)
            self.assertEqual(self.native(db, {"op": "stats"})["source_count"], 0)


if __name__ == "__main__":
    unittest.main()
