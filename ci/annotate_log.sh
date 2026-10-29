#!/usr/bin/env bash
# Surfaces a failed CI build's compiler and CMake errors as one GitHub annotation (readable without signing in to the
# job log). Usage: bash ci/annotate_log.sh build.log
set -u
log="${1:?log file}"
[ -f "$log" ] || { echo "::error title=build failed::no log at $log"; exit 0; }
lines=$(grep -nE "error|Error|FAILED|undefined reference|Undefined symbols|ld: |CMake Error" "$log" | grep -v "Werror" | head -n 60)
[ -n "$lines" ] || lines=$(tail -n 40 "$log")
# Annotations are one line: encode %, CR and LF (GitHub workflow-command escaping).
encoded=$(printf '%s' "$lines" | sed -e 's/%/%25/g' -e 's/\r/%0D/g' | awk 'BEGIN{ORS="%0A"} {print}')
echo "::error title=build failed::${encoded}"
