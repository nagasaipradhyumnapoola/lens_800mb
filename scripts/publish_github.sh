#!/usr/bin/env bash
# Publish local main to the public repo (remote lens800, branch main) as a fast-forward: every local commit made
# since the last published one is replayed onto publish/lens-800mb with the same tree and message, then pushed.
# Never force-pushes. Usage (Git Bash, from D:/Lens): bash scripts/publish_github.sh
set -euo pipefail
cd "$(dirname "$0")/.."
tip=$(git rev-parse publish/lens-800mb); tip_tree=$(git rev-parse "$tip^{tree}")
base=""
for c in $(git rev-list main); do [ "$(git rev-parse "$c^{tree}")" = "$tip_tree" ] && { base=$c; break; }; done
[ -n "$base" ] || { echo "no local commit matches the published tree; refusing" >&2; exit 1; }
n=0; msg=$(mktemp)
for c in $(git rev-list --reverse "$base..main"); do
  git log -1 --format=%B "$c" > "$msg"
  tip=$(GIT_AUTHOR_NAME="Claude Code" GIT_AUTHOR_EMAIL=noreply@anthropic.com GIT_COMMITTER_NAME="Claude Code" \
        GIT_COMMITTER_EMAIL=noreply@anthropic.com git commit-tree "$c^{tree}" -p "$tip" -F "$msg")
  n=$((n+1)); echo "  $(git log -1 --format=%s "$c" | cut -c1-90)"
done
rm -f "$msg"
[ "$n" -gt 0 ] || { echo "nothing new to publish"; exit 0; }
[ "$(git rev-parse "$tip^{tree}")" = "$(git rev-parse "main^{tree}")" ] || { echo "tree mismatch; refusing" >&2; exit 1; }
git branch -f publish/lens-800mb "$tip"
git push lens800 publish/lens-800mb:main
