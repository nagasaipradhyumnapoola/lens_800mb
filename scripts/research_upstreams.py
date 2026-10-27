"""Development-only: pin public source, license and model metadata. No inference APIs."""
import base64
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
REPOS = ["ggml-org/whisper.cpp", "cactus-compute/needle", "PaddlePaddle/PaddleOCR",
         "k2-fsa/sherpa-onnx", "sqlcipher/sqlcipher", "sqlcipher/sqlcipher-android",
         "ActivityWatch/activitywatch", "arkohut/pensieve", "asg017/sqlite-vec",
         "vercel-labs/skills"]


def get(url):
    req = Request(url, headers={"User-Agent": "Lens-Micro-build-research/0.1"})
    with urlopen(req, timeout=60) as response:
        return json.load(response)


def main():
    deps = []
    licenses = ROOT / "third_party/licenses"
    licenses.mkdir(exist_ok=True)
    for repo in REPOS:
        commit = get(f"https://api.github.com/repos/{repo}/commits/HEAD")["sha"]
        item = {"repository": repo, "url": f"https://github.com/{repo}", "commit": commit}
        try:
            lic = get(f"https://api.github.com/repos/{repo}/license?ref={commit}")
            raw = base64.b64decode(lic["content"])
            name = repo.replace("/", "--") + ".txt"
            (licenses / name).write_bytes(raw)
            item.update(license_spdx=lic["license"]["spdx_id"], license_path=lic["path"],
                        license_sha256=hashlib.sha256(raw).hexdigest())
        except Exception as exc:
            item["license_error"] = str(exc)
        deps.append(item)
        print(repo, commit, item.get("license_spdx", "REVIEW REQUIRED"), flush=True)
    (ROOT / "third_party/upstream-lock.json").write_text(
        json.dumps({"schema_version": 1, "dependencies": deps}, indent=2) + "\n", encoding="utf-8")
    for repo in ["ggerganov/whisper.cpp", "Cactus-Compute/needle3", "Cactus-Compute/needle2"]:
        meta = get(f"https://huggingface.co/api/models/{repo}/revision/main?blobs=true")
        (ROOT / "artifacts").mkdir(exist_ok=True)
        (ROOT / "artifacts" / (repo.replace("/", "--") + "-metadata.json")).write_text(
            json.dumps(meta, indent=2), encoding="utf-8")
        selected = [x for x in meta.get("siblings", []) if
                    x["rfilename"].startswith("windows-x86_64/") or
                    (x["rfilename"].endswith((".cact", ".h", "LICENSE")) and "/" not in x["rfilename"]) or
                    x["rfilename"] in ("ggml-tiny-q5_1.bin", "ggml-tiny-q8_0.bin", "ggml-base-q5_1.bin")]
        print(json.dumps({"repo": repo, "revision": meta["sha"], "files": selected}, indent=2), flush=True)


if __name__ == "__main__":
    main()
