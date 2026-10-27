"""History-import throughput and RAM on a large synthetic mailbox (docs/LENS_V1_SPEC.md §11, §15).

Generates a deterministic synthetic mbox (plain, quoted-printable, base64 and HTML parts; en/es/hi/ta/te/zh), imports it with
scripts/import-history.ps1 into a temporary encrypted database while sampling the importer + engine process tree, then
times delete-by-import. Synthetic data only; the database and mailbox live in a temp dir and are removed.

  .venv\\Scripts\\python.exe scripts/benchmark_history_import.py --emails 100000
"""
import argparse
import base64
import datetime
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import threading
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from support import pwsh  # noqa: E402

LINES = ["Orion project review is due on 3 November.", "Budget for Atlas is $12,500.", "Meeting with Priya Raman on Friday.",
         "Carlos dijo que la reunión es el 5 de noviembre.", "अरुण ने कहा कि डेडलाइन 3 नवंबर है।", "அருண் சொன்னார் கூட்டம் நவம்பர் 5.",
         "రవి గారు చెప్పారు గడువు నవంబర్ 10.", "王伟说项目的截止日期是11月3日。", "Lunch plans and travel notes for the week.",
         "Please review the attached draft and send comments."]


def message(i, rng):
    when = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(minutes=37 * i)
    date = when.strftime("%a, %d %b %Y %H:%M:%S +0000")
    body = "\n".join(rng.choice(LINES) for _ in range(rng.randint(8, 30))) + f"\nsynthetic message {i}\n"
    head = (f"From: Person {i % 997} <p{i % 997}@example.invalid>\nTo: me@example.invalid\nSubject: Synthetic subject {i}\n"
            f"Date: {date}\nMessage-ID: <m{i}@example.invalid>\nMIME-Version: 1.0\n")
    kind = i % 4
    if kind == 0:
        return head + "Content-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: base64\n\n" + base64.encodebytes(body.encode()).decode()
    if kind == 1:
        qp = "".join(f"={b:02X}" for b in body.encode())  # every byte encoded; 72 = 24 whole escapes per line
        return head + "Content-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: quoted-printable\n\n" + "=\n".join(qp[k:k + 72] for k in range(0, len(qp), 72)) + "\n"
    if kind == 2:
        return (head + 'Content-Type: multipart/alternative; boundary="b"\n\n--b\nContent-Type: text/plain; charset=utf-8\n\n'
                + body.encode().decode() + "\n--b\nContent-Type: text/html\n\n<p>" + body.replace("\n", "<br>") + "</p>\n--b--\n")
    return head + "Content-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: 8bit\n\n" + body


def sample_tree(root_pid, stop, peaks):
    while not stop.is_set():
        try:
            root = psutil.Process(root_pid)
            procs = [root] + root.children(recursive=True)
            ws = priv = 0
            for p in procs:
                try:
                    m = p.memory_info(); ws += m.rss; priv += getattr(m, "private", m.rss)
                    name = p.name().lower(); peaks[name] = max(peaks.get(name, 0), m.rss)
                except psutil.Error:
                    pass
            peaks["tree_ws"] = max(peaks.get("tree_ws", 0), ws); peaks["tree_private"] = max(peaks.get("tree_private", 0), priv)
        except psutil.Error:
            pass
        time.sleep(0.25)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emails", type=int, default=100000)
    ap.add_argument("--out", default=str(ROOT / "reports/history-import"))
    args = ap.parse_args()
    rng = random.Random(20261027)
    with tempfile.TemporaryDirectory() as tmp:
        mbox, db = Path(tmp) / "synthetic.mbox", Path(tmp) / "memory.db"
        t0 = time.perf_counter()
        with mbox.open("w", encoding="utf-8", newline="\n") as f:
            for i in range(args.emails):
                f.write("From MAILER-DAEMON Thu Jan  1 00:00:00 2020\n" + message(i, rng) + "\n")
        generate_s = time.perf_counter() - t0
        cmd = [pwsh(), "-NoProfile", "-File", str(ROOT / "scripts/import-history.ps1"), "-Format", "Mbox", "-SourcePath", str(mbox),
               "-DatabasePath", str(db), "-Progress"]
        stop, peaks = threading.Event(), {}
        t0 = time.perf_counter()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        try:
            psutil.Process(proc.pid).nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # another benchmark may share this machine
        except psutil.Error:
            pass
        watcher = threading.Thread(target=sample_tree, args=(proc.pid, stop, peaks)); watcher.start()
        out, err = proc.communicate(); stop.set(); watcher.join()
        import_s = time.perf_counter() - t0
        lines = out.splitlines(); result = json.loads(lines[-1])
        if proc.returncode or not result.get("ok"):
            raise SystemExit(f"import failed: {lines[-1][:300]}")
        engine = [str(ROOT / "build/engine/Release/lens-engine.exe"), "--db", str(db)]
        t0 = time.perf_counter()
        stats = json.loads(subprocess.run(engine, input='{"op":"stats"}\n', capture_output=True, encoding="utf-8").stdout)
        db_bytes = db.stat().st_size
        t1 = time.perf_counter()
        deleted = json.loads(subprocess.run(engine, input=json.dumps({"op": "delete_sources", "consent": True,
                             "scope": {"import": result["export_sha256"]}}) + "\n", capture_output=True, encoding="utf-8").stdout)
        delete_s = time.perf_counter() - t1
        report = {"benchmark": "history_import_mbox", "date": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                  "synthetic": True, "emails": args.emails, "mbox_bytes": mbox.stat().st_size, "generate_seconds": round(generate_s, 1),
                  "import_seconds": round(import_s, 1), "emails_per_second": round(args.emails / import_s, 1),
                  "imported": result["imported"], "batches": result["batches"], "progress_lines": len(lines) - 1,
                  "peak_tree_working_set_mb": round(peaks.get("tree_ws", 0) / 1e6, 1), "peak_tree_private_mb": round(peaks.get("tree_private", 0) / 1e6, 1),
                  "peak_pwsh_working_set_mb": round(peaks.get("pwsh.exe", 0) / 1e6, 1), "peak_engine_working_set_mb": round(peaks.get("lens-engine.exe", 0) / 1e6, 1),
                  "db_bytes_after_import": db_bytes, "bytes_per_email_in_db": round(db_bytes / max(1, stats["source_count"]), 1),
                  "source_count": stats["source_count"], "delete_by_import_seconds": round(delete_s, 1), "deleted": deleted.get("deleted"),
                  "cpu_count": os.cpu_count(), "command": " ".join(["scripts/benchmark_history_import.py", "--emails", str(args.emails)])}
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"mbox-{args.emails}-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
