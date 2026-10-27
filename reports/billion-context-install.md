# User-requested billion-context installation

Source: https://github.com/ranxianglei/billion-context.git, inspected commit
`bb7c24972c98e8f62d63726d7a3777c90a0610e1`. No SKILL.md exists in that tree.
Installed the repository's actual Codex plugin through the supported Git marketplace interface:

```powershell
codex plugin marketplace add ranxianglei/billion-context --ref bb7c24972c98e8f62d63726d7a3777c90a0610e1 --json
codex plugin add billion-context@billion-context --json
npm install --global --prefix "$env:APPDATA\npm" --ignore-scripts --no-audit --no-fund billion-context@0.1.208
codex plugin list --marketplace billion-context --json
bili --version
```

Verified installed/enabled plugin `0.1.205`, published CLI `0.1.208 (b261c333)`.
The repository's plugin manifest version differs from its CLI version. Npm reported 93 packages
installed to the existing per-user prefix; no system-wide install or lifecycle scripts were run.
The plugin launcher passes Node's syntax check, and bili prints its version and help successfully.
Npm integrity: `sha512-UxsXmDoXRFZJ5D/hyhq33QGd0dOWqA5uo/ssJLd79NH54yU7wFlb1Bf9h+b9+nzKcrfCxEo9iIibKMUzeedwDA==`.

Codex restart is required to discover the newly installed plugin. Installation does not establish
active compression. Upstream documents that compression requires a live bili proxy and model
traffic routed through it (for example, a separately launched `bili codex` session). No proxy was
started, TLS trust changed, or current conversation routed in this task. Claimed token savings
and billion-token sessions are upstream claims, not measurements of this Lens session.

This is optional Codex development tooling and is excluded from the Lens native bundle.
