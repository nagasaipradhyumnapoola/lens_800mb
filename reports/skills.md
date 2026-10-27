# Skills actually found and used

Vercel's `find-skills` was installed in `.agents/skills/find-skills` using the built-in
skill-installer. Its source is vercel-labs/skills, pinned in third_party/upstream-lock.json.
The installed file was read for this session; it becomes discoverable by Codex on the next turn.

Commands executed:

```powershell
python C:/Users/poola/.codex/skills/.system/skill-installer/scripts/list-skills.py --format json
python C:/Users/poola/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py --repo vercel-labs/skills --path skills/find-skills --dest D:/Lens/.agents/skills
npx.cmd --yes skills find 'native inference benchmarking'
npx.cmd --yes skills find 'security privacy'
```

The specialist benchmark search returned no results. The privacy search returned general/web and
regulated-domain packs; none offered a better fit than the already-installed native workflow plus
project-specific checks. Both CLI searches printed results then hit a Windows libuv shutdown
assertion; the failure is retained in skill-find-*.log.txt. No third-party search result was blindly installed.

Active instructions read: using-superpowers, brainstorming, writing-plans, modern-cpp,
test-driven-development (and writing-good-tests), systematic-debugging and
verification-before-completion. The generic security-best-practices skill was inspected but its
framework-specific coverage does not audit the native C++ engine. No frontend skill is active.

Repo-local workflows authored for the supplied requirements: lens-benchmark, lens-privacy,
lens-wear-validation, lens-release-gates. Their existence is not proof that a security/device gate passed.
The user's detailed implementation authorization takes precedence over optional planning approvals;
no speculative design approval loop was added. The requesting-code-review skill explicitly directs
dispatching an independent read-only reviewer; one scoped reviewer examined the native core.

The user later requested ranxianglei/billion-context. The repository has no SKILL.md. Its actual
Codex plugin was installed through a pinned Git marketplace (plugin 0.1.205) with the per-user
published CLI 0.1.208. Verified installed/enabled and CLI version/help; restart required. No proxy
was started or active-chat compression claimed. Details: billion-context-install.md. It is not
a Lens runtime dependency or part of the staged bundle. Plugin-management instructions were read
for discovery; the public Git plugin was installed with Codex's supported CLI.
