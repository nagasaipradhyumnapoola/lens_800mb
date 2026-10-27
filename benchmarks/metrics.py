"""Transparent, script-preserving metrics (not Whisper's English normalizer)."""
import unicodedata


def normalize(text):
    text = unicodedata.normalize("NFC", str(text)).casefold()
    return " ".join("".join(" " if unicodedata.category(c)[0] in "PS" else c
                            for c in text).split())


def error_rate(reference, hypothesis, chars=False):
    ref, hyp = normalize(reference), normalize(hypothesis)
    a, b = (list(ref.replace(" ", "")), list(hyp.replace(" ", ""))) if chars else (ref.split(), hyp.split())
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        nxt = [i]
        for j, y in enumerate(b, 1):
            nxt.append(min(nxt[-1] + 1, row[j] + 1, row[j - 1] + (x != y)))
        row = nxt
    return row[-1], len(a)


def field_scores(expected, actual):
    # Null/missing are abstentions, not invented facts. Wrong values count FP and FN.
    exp = {(k, normalize(v)) for k, v in expected.items() if v is not None}
    got = {(k, normalize(v)) for k, v in actual.items() if v is not None}
    tp, fp, fn = len(exp & got), len(got - exp), len(exp - got)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0}


def release_status(installed_bytes, peak_ram_bytes, sample_count, failures):
    """Historical 500 MB baseline; revised user release decisions are in report-results.py."""
    if failures or (installed_bytes is not None and installed_bytes > 500_000_000) or \
            (peak_ram_bytes is not None and peak_ram_bytes > 500_000_000):
        return "FAIL"
    if installed_bytes is None or peak_ram_bytes is None or sample_count < 100:
        return "PENDING"
    return "PASS"
