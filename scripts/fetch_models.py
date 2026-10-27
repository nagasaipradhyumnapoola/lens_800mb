"""Fetch immutable public artifacts and check upstream hashes before executing anything."""
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def fetch(repo, revision, item):
    name = item["rfilename"]
    target = ROOT / "models" / repo.replace("/", "--") / name
    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/{repo}/resolve/{revision}/{name}"
    if not target.exists():
        part = target.with_name(target.name + ".part")
        with urlopen(Request(url, headers={"User-Agent": "Lens-Micro-build/0.1"}), timeout=120) as src:
            with part.open("wb") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
        part.replace(target)
    raw = target.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    expected = item.get("lfs", {}).get("sha256")
    if expected and sha != expected:
        raise ValueError(f"SHA256 mismatch: {target}")
    if not expected:
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if blob != item["blobId"]:
            raise ValueError(f"Git blob mismatch: {target}")
    if len(raw) != item["size"]:
        raise ValueError(f"Size mismatch: {target}")
    result = {"repo": repo, "revision": revision, "filename": name, "url": url,
              "path": target.relative_to(ROOT).as_posix(), "bytes": len(raw), "sha256": sha,
              "upstream_verification": "lfs-sha256" if expected else "git-blob-sha1"}
    print(name, len(raw), sha, flush=True)
    return result


def main():
    records = []
    for repo in ("ggerganov/whisper.cpp", "Cactus-Compute/needle3", "Cactus-Compute/needle2"):
        meta = json.loads((ROOT / "artifacts" / (repo.replace("/", "--") + "-metadata.json")).read_text())
        for item in meta["siblings"]:
            name = item["rfilename"]
            if name in ("ggml-tiny-q5_1.bin", "ggml-tiny-q8_0.bin", "ggml-base-q5_1.bin",
                        "needle3.cact", "needle2.cact", "LICENSE", "windows-x86_64/needle.exe",
                        "windows-x86_64/needle.h", "python/cactus_needle-3.3.3-py3-none-win_amd64.whl"):
                records.append(fetch(repo, meta["sha"], item))
                if name.endswith("3.3.3-py3-none-win_amd64.whl"):
                    import zipfile
                    with zipfile.ZipFile(ROOT / records[-1]["path"]) as archive:
                        raw = archive.read("needle/libneedle3.dll")
                    target = ROOT / "models/Cactus-Compute--needle3/windows-x86_64/libneedle3.dll"
                    target.write_bytes(raw)
                    records.append({"repo": repo, "revision": meta["sha"], "filename": "windows-x86_64/libneedle3.dll",
                                    "path": target.relative_to(ROOT).as_posix(), "bytes": len(raw),
                                    "sha256": hashlib.sha256(raw).hexdigest(), "source": name,
                                    "upstream_verification": "member of verified wheel"})
    (ROOT / "models/manifest.lock.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    (ROOT / "third_party/model-lock.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
