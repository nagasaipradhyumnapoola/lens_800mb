"""Reuse Microsoft's sqlcipher port with the current upstream release pinned by digest."""
import hashlib
import json
from pathlib import Path
import shutil
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
VERSION = "4.19.0"
URL = f"https://github.com/sqlcipher/sqlcipher/archive/refs/tags/v{VERSION}.tar.gz"


def main():
    source = ROOT / "third_party/vcpkg/ports/sqlcipher"
    target = ROOT / "third_party/overlays/sqlcipher"
    if target.exists():
        print("Overlay already prepared; inspect its lock rather than overwriting")
        return
    with urlopen(URL, timeout=120) as response:
        data = response.read()
    sha = hashlib.sha512(data).hexdigest()
    shutil.copytree(source, target)
    port = target / "portfile.cmake"
    text = port.read_text(encoding="utf-8")
    import re
    text = re.sub(r"SHA512 [0-9a-f]+", "SHA512 " + sha, text)
    port.write_text(text, encoding="utf-8")
    config_path = target / "vcpkg.json"
    config = json.loads(config_path.read_text())
    config["version"] = VERSION
    config.pop("port-version", None)
    config["license"] = "BSD-3-Clause"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    cmake=target/'CMakeLists.txt'
    cmake.write_text(cmake.read_text(encoding='utf-8').replace('-DSQLITE_HAS_CODEC',
        '-DSQLITE_HAS_CODEC\n        -DSQLITE_EXTRA_INIT=sqlcipher_extra_init\n        -DSQLITE_EXTRA_SHUTDOWN=sqlcipher_extra_shutdown\n        -DSQLITE_THREADSAFE=1'),encoding='utf-8')
    (target / "lens-provenance.json").write_text(json.dumps({
        "source": "microsoft/vcpkg", "commit": "817892b0ecbc6af994dd6df999c73faf795adbf2",
        "path": "ports/sqlcipher", "changes": "release version, archive digest, and mandatory 4.19 initialization/shutdown/thread-safety definitions",
        "sqlcipher_release": VERSION, "url": URL, "sha512": sha}, indent=2), encoding="utf-8")
    print(VERSION, sha)


if __name__ == "__main__":
    main()
