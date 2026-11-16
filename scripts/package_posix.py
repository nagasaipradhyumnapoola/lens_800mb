"""Stage Lens for macOS (Lens.app) or Linux (a folder with install.sh), from a CI build (docs/LENS_V1_SPEC.md §18).

lens-agent finds its install root as the nearest folder above its executable that holds third_party/embedding-lock.json
(the same rule as scripts/package_lens.py on Windows), so models/ and third_party/ sit at the root and the programs one
level below it:
  macOS: Lens.app/Contents/{MacOS/: programs, libraries, ui/; Resources/AppIcon.icns; Info.plist; models/; third_party/}
  Linux: Lens/{bin/: programs, libraries, ui/; models/; third_party/; install.sh; uninstall.sh; lens.png; README.txt}
Models are copied when present and matching their lock files; a CI build has none, so recall is keyword-only and OCR and
speech report themselves unavailable until the models are added. Libraries the programs link from outside the build
(Homebrew on macOS) are bundled afterwards by the CI job (dylibbundler); Linux uses the distribution's libraries.
Usage: python3 scripts/package_posix.py --platform macos|linux --bin build/macos/bin --out dist
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from package_lens import VERSION, lock_files  # noqa: E402  (one list of the product's models)
SKIP={'lens-observer-testapp','lens-embed'}  # test window and development tool
LOCKS=['embedding-lock.json','reranker-lock.json','ocr-runtime-lock.json','model-lock.json','upstream-lock.json','build-lock.json',
       'sherpa-reference-lock.json']
ICON=ROOT/'apple/Lens/Assets.xcassets/AppIcon.appiconset/icon-1024.png'


def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()


INFO_PLIST='''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Lens</string>
  <key>CFBundleDisplayName</key><string>Lens</string>
  <key>CFBundleIdentifier</key><string>org.secondbrain.lens.desktop</string>
  <key>CFBundleExecutable</key><string>lens-app</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>{version}</string>
  <key>CFBundleVersion</key><string>{version}</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Lens listens only while you hold the microphone on, to turn speech into text on this Mac.</string>
</dict></plist>
'''

INSTALL_SH='''#!/bin/sh
# Installs Lens for this user only (no root): ~/.local/share/lens, a launcher in the applications menu and ~/.local/bin/lens.
# Your memory lives in Lens's data folder and is never touched by install or uninstall.
set -e
here=$(cd "$(dirname "$0")" && pwd)
dest="${XDG_DATA_HOME:-$HOME/.local/share}/lens"
mkdir -p "$dest" "$HOME/.local/bin" "${XDG_DATA_HOME:-$HOME/.local/share}/applications"
cp -R "$here/bin" "$here/third_party" "$dest/"
[ -d "$here/models" ] && cp -R "$here/models" "$dest/"
cp "$here/lens.png" "$here/uninstall.sh" "$here/manifest.json" "$dest/"
ln -sf "$dest/bin/lens-app" "$HOME/.local/bin/lens"
cat > "${XDG_DATA_HOME:-$HOME/.local/share}/applications/lens.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Lens
Comment=Your private memory: ask what you saw, said and noted
Exec=$dest/bin/lens-app
Icon=$dest/lens.png
Categories=Utility;Office;
Terminal=false
EOF
echo "Lens installed. Open it from your applications menu, or run: lens"
'''

UNINSTALL_SH='''#!/bin/sh
# Removes the Lens programs and launcher for this user. Your memory (Lens's data folder) is kept; delete it from the app first.
dest="${XDG_DATA_HOME:-$HOME/.local/share}/lens"
pkill -u "$(id -u)" -x lens-agent 2>/dev/null || true
rm -rf "$dest" "$HOME/.local/bin/lens" "${XDG_DATA_HOME:-$HOME/.local/share}/applications/lens.desktop"
echo "Lens removed. Your memory was kept."
'''

README_TXT='''Lens {version} for Linux (x86_64), built on Ubuntu 24.04.
Install for this user: ./install.sh      Remove: ~/.local/share/lens/uninstall.sh
Needs the distribution's libraries: GTK 4, WebKitGTK 6.0, libsecret, zstd, utf8proc, OpenSSL 3, AT-SPI and X11
(Ubuntu/Debian: sudo apt install libgtk-4-1 libwebkitgtk-6.0-4 libsecret-1-0 libzstd1 libutf8proc3 libssl3t64 libatspi2.0-0t64).
The database key is kept in your login keyring (Secret Service); a desktop session with an unlocked keyring is required.
'''


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--platform',choices=['macos','linux'],required=True)
    ap.add_argument('--bin',type=Path,required=True)
    ap.add_argument('--out',type=Path,default=ROOT/'dist')
    a=ap.parse_args()
    if a.platform=='macos':
        top=a.out/'Lens.app';root=top/'Contents';programs=root/'MacOS'
    else:
        top=root=a.out/'Lens';programs=root/'bin'
    if top.exists():shutil.rmtree(top)
    programs.mkdir(parents=True)
    for p in sorted(a.bin.iterdir()):
        if p.name in SKIP:continue
        if p.is_dir():
            if p.name=='ui':shutil.copytree(p,programs/'ui')
            continue
        shutil.copy2(p,programs/p.name,follow_symlinks=True)
    models=0
    for rel,expected in lock_files():
        src=ROOT/rel
        if src.exists() and sha(src)==expected:
            dst=root/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst);models+=1
    (root/'third_party').mkdir(exist_ok=True)
    for name in LOCKS:shutil.copy2(ROOT/'third_party'/name,root/'third_party'/name)
    shutil.copytree(ROOT/'third_party/licenses',root/'third_party/licenses')
    if a.platform=='macos':
        (root/'Info.plist').write_text(INFO_PLIST.format(version=VERSION),encoding='utf-8')
        res=root/'Resources';res.mkdir()
        if shutil.which('iconutil'):  # AppIcon.icns from the iPhone app's icon
            iconset=a.out/'AppIcon.iconset';iconset.mkdir(exist_ok=True)
            for size in (16,32,128,256,512):
                for scale in (1,2):
                    name=f'icon_{size}x{size}{"@2x" if scale==2 else ""}.png'
                    subprocess.run(['sips','-z',str(size*scale),str(size*scale),str(ICON),'--out',str(iconset/name)],check=True,capture_output=True)
            subprocess.run(['iconutil','-c','icns',str(iconset),'-o',str(res/'AppIcon.icns')],check=True)
            shutil.rmtree(iconset)
    else:
        for name,text in (('install.sh',INSTALL_SH),('uninstall.sh',UNINSTALL_SH)):
            (root/name).write_text(text,encoding='utf-8');(root/name).chmod(0o755)
        (root/'README.txt').write_text(README_TXT.format(version=VERSION),encoding='utf-8')
        shutil.copy2(ICON,root/'lens.png')
    files=sorted(p for p in root.rglob('*') if p.is_file())
    manifest={'product':'Lens','version':VERSION,'platform':a.platform,'models_included':models,
              'files':[{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in files]}
    manifest['installed_bytes']=sum(f['bytes'] for f in manifest['files'])
    (root/'manifest.json').write_text(json.dumps(manifest,indent=1),encoding='utf-8')
    print(json.dumps({'package':str(top),'files':len(files),'models':models,'installed_bytes':manifest['installed_bytes']}))


if __name__=='__main__':main()
