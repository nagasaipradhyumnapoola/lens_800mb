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


# ---------------------------------------------------------------- formats added for docs/LENS_V1_SPEC.md §11
def mime_message(i, subject="Orion budget review", body="Synthetic mailanchor body", date="Tue, 27 Oct 2026 09:00:00 +0530",
                 sender='"Arun Kumar" <arun@example.invalid>', message_id=None, extra_headers=""):
    mid = message_id or f"<msg-{i}@example.invalid>"
    return (f"From: {sender}\nTo: me@example.invalid\nSubject: {subject}\nDate: {date}\nMessage-ID: {mid}\n{extra_headers}"
            f"MIME-Version: 1.0\nContent-Type: text/plain; charset=utf-8\n\n{body}\n")


def mbox(messages):
    return "".join(f"From MAILER-DAEMON Tue Oct 27 09:00:00 2026\n{m}\n" for m in messages)


def pdf_bytes(lines, created="D:20261027090000+05'30'", hex_only=False):
    import zlib
    ops = "BT /F1 12 Tf 72 712 Td " + " T* ".join(
        ("<%s> Tj" % line.encode("latin-1").hex()) if hex_only else "(%s) Tj" % line.replace("(", r"\(").replace(")", r"\)") for line in lines) + " ET"
    stream = zlib.compress(ops.encode("latin-1"))
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
               b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream) + stream + b"\nendstream",
               ("<< /CreationDate (%s) >>" % created).encode("latin-1")]
    out = bytearray(b"%PDF-1.4\n")
    for n, body in enumerate(objects, 1):
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    out += b"trailer\n<< /Root 1 0 R /Info 5 0 R >>\n%%EOF\n"
    return bytes(out)


class NewFormats(unittest.TestCase):
    invoke, successful, rejected, native, sources, write = (HistoryImport.invoke, HistoryImport.successful, HistoryImport.rejected,
                                                          HistoryImport.native, HistoryImport.sources, HistoryImport.write)

    def test_mbox_mime_decoding_dedup_skips_and_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            qp = ("From: =?UTF-8?B?UHJpeWEgUmFtYW4=?= <priya@example.invalid>\nTo: me@example.invalid\n"
                  "Subject: =?UTF-8?Q?Caf=C3=A9_plan?=\nDate: Mon, 26 Oct 2026 18:30:00 +0000\nMessage-ID: <qp@example.invalid>\n"
                  "MIME-Version: 1.0\nContent-Type: multipart/alternative; boundary=\"b1\"\n\n--b1\n"
                  "Content-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: quoted-printable\n\n"
                  "Caf=C3=A9 qpanchor =E5=8C=97=E4=BA=AC\n>From the start\n--b1\nContent-Type: text/html\n\n<p>html version</p>\n--b1--\n")
            b64 = ("From: Ravi <ravi@example.invalid>\nSubject: Base64 note\nDate: 25 Oct 2026 08:00:00 GMT\nMessage-ID: <b64@example.invalid>\n"
                   "Content-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: base64\n\n"
                   + __import__("base64").b64encode("b64anchor మీటింగ్ రేపు".encode()).decode() + "\n")
            html_only = ("From: Meena <meena@example.invalid>\nSubject: Html only\nDate: Sat, 24 Oct 2026 10:00:00 -0400 (EDT)\n"
                         "Message-ID: <h@example.invalid>\nContent-Type: text/html; charset=iso-8859-1\n\n<p>htmlanchor &amp; caf\xe9</p><script>x()</script>\n")
            body = mbox([mime_message(1), qp, b64, html_only, mime_message(1), mime_message(2, date="")])
            source = Path(tmp) / "synthetic.mbox"
            source.write_bytes(body.encode("latin-1"))  # one message is ISO-8859-1, the rest ASCII
            db = Path(tmp) / "memory.db"
            p = self.invoke(source, db, "Mbox", "-Preview")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            preview = json.loads(p.stdout)
            self.assertEqual((preview["records"], preview["duplicates_in_file"], preview["skipped"]), (4, 1, {"missing_or_invalid_date": 1}))
            self.assertEqual(preview["sample"][0]["title"], "Orion budget review")
            self.assertFalse(db.exists())
            result = self.successful(source, db, "Mbox")
            self.assertEqual((result["imported"], result["duplicates_in_file"]), (4, 1))
            row = self.sources(db, "qpanchor")[0]
            self.assertIn("Café qpanchor 北京", row["text"]); self.assertIn("From the start", row["text"])
            self.assertTrue(row["text"].startswith("Subject: Café plan\nFrom: Priya Raman"))
            self.assertEqual(row["metadata"]["sender"], "Priya Raman"); self.assertEqual(row["timestamp"], "2026-10-26T18:30:00+00:00")
            self.assertEqual(row["kind"], "imported_email"); self.assertEqual(row["source_application"], "Email")
            self.assertIn("b64anchor మీటింగ్ రేపు", self.sources(db, "b64anchor")[0]["text"])
            html = self.sources(db, "htmlanchor")[0]
            self.assertIn("htmlanchor & café", html["text"]); self.assertNotIn("x()", html["text"])
            self.assertEqual(html["timestamp"], "2026-10-24T10:00:00-04:00")
            self.assertEqual(self.sources(db, "mailanchor")[0]["timestamp"], "2026-10-27T09:00:00+05:30")
            self.assertEqual(self.successful(source, db, "Mbox")["deduplicated"], 4)

    def test_single_eml(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.write(tmp, mime_message(9, body="emlanchor single message"), "synthetic.eml")
            db = Path(tmp) / "memory.db"
            self.assertEqual(self.successful(source, db, "Eml")["imported"], 1)
            self.assertEqual(self.sources(db, "emlanchor")[0]["metadata"]["sender"], "Arun Kumar")

    def test_calendar_zones_all_day_and_floating_times(self):
        ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:e1\r\nDTSTART;TZID=Asia/Kolkata:20261103T093000\r\nSUMMARY:Orion review icsanchor\r\n"
               "LOCATION:Chennai office\\, room 4\r\nORGANIZER;CN=Meena Iyer:mailto:meena@example.invalid\r\nDESCRIPTION:Bring the budget\\nand slides\r\nEND:VEVENT\r\n"
               "BEGIN:VEVENT\r\nUID:e2\r\nDTSTART:20261104T120000Z\r\nSUMMARY:Utc call icsanchor\r\nEND:VEVENT\r\n"
               "BEGIN:VEVENT\r\nUID:e3\r\nDTSTART;VALUE=DATE:20261105\r\nSUMMARY:Holiday icsanchor\r\nRRULE:FREQ=YEARLY\r\nEND:VEVENT\r\n"
               "BEGIN:VEVENT\r\nUID:e1\r\nDTSTART;TZID=Asia/Kolkata:20261103T093000\r\nSUMMARY:Orion review icsanchor\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        with tempfile.TemporaryDirectory() as tmp:
            source = self.write(tmp, ics, "synthetic.ics")
            db = Path(tmp) / "memory.db"
            result = self.successful(source, db, "Ics")
            self.assertEqual((result["imported"], result["duplicates_in_file"]), (3, 1))
            rows = {r["metadata"]["uid"]: r for r in self.sources(db, "icsanchor")}
            self.assertEqual(rows["e1"]["timestamp"], "2026-11-03T09:30:00+05:30")
            self.assertIn("Where: Chennai office, room 4", rows["e1"]["text"]); self.assertIn("Bring the budget\nand slides", rows["e1"]["text"])
            self.assertEqual(rows["e1"]["metadata"]["organizer"], "Meena Iyer"); self.assertEqual(rows["e1"]["kind"], "imported_event")
            self.assertEqual(rows["e2"]["timestamp"], "2026-11-04T12:00:00+00:00")
            self.assertTrue(rows["e3"]["metadata"]["all_day"]); self.assertEqual(rows["e3"]["metadata"]["recurrence_rule"], "FREQ=YEARLY")
            floating = self.write(tmp, "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:f\r\nDTSTART:20261103T093000\r\nSUMMARY:Floating\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n", "f.ics")
            db2 = Path(tmp) / "floating.db"
            self.assertEqual(json.loads(self.rejected(floating, db2, "Ics").stdout)["error"], "source_timezone_required")
            self.successful(floating, db2, "Ics", "-SourceTimeZone", "UTC+05:30")
            self.assertEqual(self.native(db2, {"op": "stats"})["source_count"], 1)

    def test_contacts(self):
        vcf = ("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Arun Kumar\r\nN:Kumar;Arun;;;\r\nORG:Acme Labs\r\nTITLE:Lead\r\nTEL;TYPE=cell:+1 555 0100\r\n"
               "EMAIL:arun@example.invalid\r\nREV:20261001T120000Z\r\nUID:c1\r\nNOTE:vcfanchor met at the Orion kickoff\r\nEND:VCARD\r\n"
               "BEGIN:VCARD\r\nVERSION:2.1\r\nN:Iyer;Meena\r\nNOTE;ENCODING=QUOTED-PRINTABLE;CHARSET=UTF-8:vcfanchor caf=C3=A9\r\nEND:VCARD\r\n"
               "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Arun Kumar\r\nUID:c1\r\nEND:VCARD\r\n")
        with tempfile.TemporaryDirectory() as tmp:
            source = self.write(tmp, vcf, "synthetic.vcf")
            db = Path(tmp) / "memory.db"
            result = self.successful(source, db, "Vcf")
            self.assertEqual((result["imported"], result["duplicates_in_file"]), (2, 1))
            rows = {r["metadata"]["contact_name"]: r for r in self.sources(db, "vcfanchor")}
            self.assertIn("Organization: Acme Labs", rows["Arun Kumar"]["text"]); self.assertEqual(rows["Arun Kumar"]["timestamp"], "2026-10-01T12:00:00+00:00")
            self.assertIn("vcfanchor café", rows["Iyer Meena"]["text"]); self.assertIsNone(rows["Iyer Meena"]["original_timestamp"])
            self.assertEqual(rows["Iyer Meena"]["metadata"]["timestamp_basis"], "import_time")

    def test_browser_history_drops_query_tokens(self):
        takeout = {"Browser History": [
            {"title": "Orion docs browseranchor", "url": "https://docs.example.invalid/orion/plan?session=SECRETTOKEN123#top", "time_usec": 1793092800000000},
            {"title": "Local file", "url": "file:///C:/private.txt", "time_usec": 1793092800000000},
            {"title": "Orion docs browseranchor", "url": "https://docs.example.invalid/orion/plan?other=1", "time_usec": 1793092800000000}]}
        with tempfile.TemporaryDirectory() as tmp:
            source = self.write(tmp, json.dumps(takeout), "BrowserHistory.json")
            db = Path(tmp) / "memory.db"
            result = self.successful(source, db, "BrowserHistory")
            self.assertEqual((result["imported"], result["duplicates_in_file"], result["skipped"]), (1, 1, {"unsupported_url": 1}))
            row = self.sources(db, "browseranchor")[0]
            self.assertEqual(row["text"], "Orion docs browseranchor\nhttps://docs.example.invalid/orion/plan")
            self.assertTrue(row["metadata"]["query_removed"]); self.assertEqual(row["timestamp"], __import__("datetime").datetime.fromtimestamp(1793092800, __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"))
            self.assertEqual(self.native(db, {"op": "search", "query": "SECRETTOKEN123"})["sources"], [])
            csv = self.write(tmp, "url,title,visit_time\nhttps://example.invalid/a,csvanchor page,1793092800000\n", "history.csv")
            db2 = Path(tmp) / "csv.db"
            self.successful(csv, db2, "BrowserHistory")
            self.assertEqual(self.sources(db2, "csvanchor")[0]["timestamp"], __import__("datetime").datetime.fromtimestamp(1793092800, __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"))

    def test_pdf_text_and_unsupported_pdfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "synthetic.pdf"
            source.write_bytes(pdf_bytes(["Synthetic pdfanchor report (draft)", "Orion review is due on 3 November."]))
            db = Path(tmp) / "memory.db"
            self.assertEqual(self.successful(source, db, "Pdf")["imported"], 1)
            row = self.sources(db, "pdfanchor")[0]
            self.assertEqual(row["text"], "Synthetic pdfanchor report (draft)\nOrion review is due on 3 November.")
            self.assertEqual(row["timestamp"], "2026-10-27T09:00:00+05:30"); self.assertEqual(row["kind"], "imported_document")
            scanned = Path(tmp) / "hex.pdf"
            scanned.write_bytes(pdf_bytes(["hidden"], hex_only=True))
            self.assertEqual(json.loads(self.rejected(scanned, db, "Pdf").stdout)["error"], "pdf_text_unavailable")
            junk = self.write(tmp, "not a pdf", "junk.pdf")
            self.assertEqual(json.loads(self.rejected(junk, db, "Pdf").stdout)["error"], "unsupported_pdf")

    def test_progress_cancellation_mid_stream_and_delete_by_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "big.mbox"
            source.write_text(mbox([mime_message(i, body=f"bulkanchor message {i}") for i in range(600)]), encoding="utf-8")
            db = Path(tmp) / "memory.db"; cancel = Path(tmp) / "cancel.flag"
            proc = subprocess.Popen([pwsh(), "-NoProfile", "-File", str(SCRIPT), "-Format", "Mbox", "-SourcePath", str(source),
                                     "-DatabasePath", str(db), "-Progress", "-CancelPath", str(cancel)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            first = json.loads(proc.stdout.readline())
            self.assertGreaterEqual(first["progress"]["records"], 128)  # a chunk was written inside the open transaction
            cancel.write_text("cancel")
            rest = proc.stdout.read().splitlines(); proc.wait(timeout=120)
            final = json.loads(rest[-1])
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual((final["error"], final["outcome"], final["imported"]), ("cancelled", "rolled_back", 0))
            self.assertEqual(self.native(db, {"op": "stats"})["source_count"], 0)
            cancel.unlink()
            p = self.invoke(source, db, "Mbox", "-Progress")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            lines = p.stdout.splitlines(); result = json.loads(lines[-1])
            self.assertGreaterEqual(len(lines), 5); self.assertEqual(result["imported"], 600)
            ics = self.write(tmp, "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:k\r\nDTSTART:20261104T120000Z\r\nSUMMARY:Keepanchor\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n", "k.ics")
            self.successful(ics, db, "Ics")
            imports = {x["export_sha256"]: x for x in self.native(db, {"op": "imports"})["imports"]}
            self.assertEqual(imports[result["export_sha256"]]["sources"], 600); self.assertEqual(imports[result["export_sha256"]]["format"], "Mbox")
            deleted = self.native(db, {"op": "delete_sources", "consent": True, "scope": {"import": result["export_sha256"]}})
            self.assertEqual(deleted["deleted"], 600)
            self.assertEqual(self.native(db, {"op": "stats"})["source_count"], 1)
            self.assertEqual(len(self.sources(db, "Keepanchor")), 1)


if __name__ == "__main__":
    unittest.main()
