#!/usr/bin/env bash
# Screenshots of the iPhone and Apple Watch apps on simulators, in demo mode (-LensDemo YES: a separate memory with
# synthetic items and no laptop; apple/Shared/Core.swift LensPaths.demo). Run from the repository root after the apps were
# built for the simulators into build/dd (.github/workflows/portable.yml, job ios-screens). Usage: ci/ios/screenshots.sh <out>
set -euo pipefail
trap 'echo "::error title=iOS screenshots::failed at line $LINENO: $BASH_COMMAND"' ERR  # annotations are readable without sign-in
crashes() {  # a crashed app shows the home screen; report its crash log as an annotation
  for f in "$HOME"/Library/Logs/DiagnosticReports/Lens*; do
    [ -e "$f" ] && echo "::error title=Lens crashed::$(basename "$f"): $(grep -m3 -E 'exception|Exception|termination|Crashed' "$f" | tr '\n' ' ' | cut -c1-600)"
  done; return 0
}
trap crashes EXIT
out=${1:-screenshots}; mkdir -p "$out"
products=build/dd/Build/Products
pick() {  # newest runtime of a platform, first device whose name starts with a prefix
  xcrun simctl list devices available -j | python3 -c "
import json, sys
d = json.load(sys.stdin)['devices']
print(next(x['udid'] for r, l in sorted(d.items(), reverse=True) if '$1' in r for x in l if x['name'].startswith('$2')))"
}

phone=$(pick iOS "iPhone 16")
xcrun simctl boot "$phone"; xcrun simctl bootstatus "$phone" -b
xcrun simctl status_bar "$phone" override --time 9:41 --batteryState charged --batteryLevel 100 --cellularBars 4 --wifiBars 3
xcrun simctl install "$phone" "$products/Debug-iphonesimulator/Lens.app"
shot() {  # shot <name> <seconds to settle> <launch arguments...>
  local name=$1 wait=$2; shift 2
  xcrun simctl terminate "$phone" org.secondbrain.lens 2>/dev/null || true
  xcrun simctl launch "$phone" org.secondbrain.lens -LensDemo YES "$@" >/dev/null
  sleep "$wait"
  xcrun simctl io "$phone" screenshot "$out/iphone-$name.png" >/dev/null
  echo "iphone-$name.png"
}
shot onboarding 8 -LensOnboarding YES   # first launch also fills the demo memory
shot ask 10 -LensTab 0 -LensAsk "When is the dentist appointment?"
shot remember 5 -LensTab 1
shot memories 6 -LensTab 2
shot settings 5 -LensTab 3
shot pair 6 -LensTab 3 -LensPair YES
xcrun simctl ui "$phone" appearance dark
shot ask-dark 10 -LensTab 0 -LensAsk "Which flight did I book?"
shot memories-dark 6 -LensTab 2

watch=$(pick watchOS "Apple Watch")
xcrun simctl boot "$watch"; xcrun simctl bootstatus "$watch" -b
xcrun simctl install "$watch" "$products/Debug-watchsimulator/LensWatch.app"
xcrun simctl launch "$watch" org.secondbrain.lens.watchkitapp -LensDemo YES >/dev/null
sleep 8
xcrun simctl io "$watch" screenshot "$out/watch-answer.png" >/dev/null && echo watch-answer.png
