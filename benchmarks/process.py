"""Process-tree sampling for development; OS high-water counters supplement samples."""
import os
import subprocess
import threading
import time
import psutil


def measure(command, timeout=180, cwd=None, input_data=None):
    env = os.environ.copy()
    env.update(NEEDLE_TELEMETRY="0", DO_NOT_TRACK="1", HF_HUB_OFFLINE="1",
               HF_HUB_DISABLE_TELEMETRY="1", OMP_NUM_THREADS="2")
    start = time.perf_counter()
    process = subprocess.Popen([str(x) for x in command], cwd=cwd, env=env,
                               stdin=subprocess.PIPE if input_data is not None else None,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result = {}

    def collect():
        result["stdout"], result["stderr"] = process.communicate(input=input_data)

    thread = threading.Thread(target=collect, daemon=True)
    thread.start()
    known, peaks = {}, {}
    peak_rss = peak_private = samples = 0
    timed_out = False
    while process.poll() is None:
        try:
            root = psutil.Process(process.pid)
            for p in [root] + root.children(recursive=True):
                known[(p.pid, p.create_time())] = p
        except psutil.Error:
            pass
        rss = private = 0
        for identity, p in list(known.items()):
            try:
                if p.create_time() != identity[1]:
                    continue
                mem = p.memory_info()
                rss += mem.rss
                private += getattr(mem, "private", mem.vms)
                a, b = peaks.get(identity, (0, 0))
                peaks[identity] = (max(a, getattr(mem, "peak_wset", mem.rss)),
                                   max(b, getattr(mem, "peak_pagefile", mem.vms)))
            except psutil.Error:
                pass
        peak_rss, peak_private = max(peak_rss, rss), max(peak_private, private)
        samples += 1
        if time.perf_counter() - start > timeout:
            timed_out = True
            for p in reversed(list(known.values())):
                try:
                    p.kill()
                except psutil.Error:
                    pass
            process.kill()
            break
        time.sleep(.01)
    thread.join(timeout=10)
    if thread.is_alive():
        raise RuntimeError("Output collector did not finish; descendant may retain a pipe")
    return {"command": [str(x) for x in command], "exit_code": process.returncode,
            "timed_out": timed_out, "wall_ms": (time.perf_counter() - start) * 1000,
            "sampled_tree_rss_peak_bytes": peak_rss, "sampled_tree_private_peak_bytes": peak_private,
            "sum_observed_process_peak_wset_bytes": sum(x[0] for x in peaks.values()),
            "sum_observed_process_peak_commit_bytes": sum(x[1] for x in peaks.values()),
            "observed_processes": len(known), "sample_count": samples,
            "sampling_interval_ms": 10, "stdout": result.get("stdout", b"").decode("utf-8", "replace"),
            "stderr": result.get("stderr", b"").decode("utf-8", "replace")}
