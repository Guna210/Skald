# Orchestrator log — CONTEXT.md

File 1. First entry: E-0001. Previous file: none.
Append-only. Mistakes are corrected by a new `CORRECTION` entry, never by editing.
Times are Asia/Colombo.

---

### E-0001 · 2026-11-12 23:31 (Asia/Colombo) · — · NOTE
Context: First Orchestrator session. Owner said "you are the orchestrator, read the files and get up to speed". Read `CLAUDE.md`, `AGENTS.md` and `SPEC.md` v1.0 (16 Oct 2026) in full and checked the repo.
Decision: Created this orphan branch `orchestrator` with `STATE.md` and `CONTEXT.md`, as `CLAUDE.md` ("Orchestrator memory") requires.
Why: No memory branch existed; later sessions start from `STATE.md`.
Repo state found: 2 commits (`34c9786` Init, `e8de66b` Update SPEC.md cloud environment setup); files are only `AGENTS.md`, `CLAUDE.md`, `SPEC.md`; one remote branch, `master`; no PRs, no releases, no tags. Every task in SPEC Part D is unticked. Clarifications log (Appendix 3) is empty.
Cloud environment "Skald" matches SPEC Appendix 4 (allowed hosts and setup script); the session has Python 3.12.3, Node 22.23.4, uv 0.11.32.
Follow-up: E-0002, E-0003.

### E-0002 · 2026-11-12 23:31 (Asia/Colombo) · — · OWNER-ACTION
Context: The repo's only branch is `master`, but `SPEC.md`, `AGENTS.md` and `CLAUDE.md` all assume `main` (Builders branch from `main`, ticks are read on `main`, the catalog URL and the Colab link point at `main`).
Decision: Asked the owner to rename the default branch `master` → `main` in GitHub settings before T00.1 starts. Not changing the docs to say `master`.
Why: One rename is cheaper and less error-prone than editing three documents, and a GitHub setting is an owner-only action.
Follow-up: confirm `main` exists before issuing the T00.1 Builder prompt.

### E-0003 · 2026-11-12 23:31 (Asia/Colombo) · — · QUESTION
Context: `SPEC.md` header says "Status: Draft for owner approval".
Decision: Asked the owner to confirm the spec is approved as written (v1.0). If yes, the T00.1 Builder updates the status line in its PR and logs it in Appendix 3.
Why: Part A decisions become final only once approved; Builders should not build against a draft.
Follow-up: owner's answer.

### E-0004 · 2026-11-12 23:31 (Asia/Colombo) · T00.1 · NOTE
Context: Things noticed while reading that will go into Builder prompts (no spec change needed yet).
Notes:
- Claude cloud sessions are given their own `claude/<name>` working branch by the platform and told not to push elsewhere without permission. Builder prompts must say plainly that the owner authorizes pushing to `task/<ID>-<slug>` and opening the PR. Same for the Reviewer: read-only, no pushes.
- T00.1 "tree matches B3": B3 also lists files that later tasks create (`catalog.json`, `deps.lock.json`, `pyproject.toml`, the notebook, workflows…). Reading for T00.1: create the directories (with `.gitkeep`) and only the files T00.1's Do list names; other files arrive with their own tasks.
- T00.1 vendors Ponytail from `DietrichGebert/ponytail` at `84740e3d344b69b4a133201fa519eb37a62a2b2a`. Not verified from this session (outside its GitHub scope). If the commit or paths can't be fetched, the Builder stops and asks.
- `<owner>` placeholders in the spec = `Guna210` (catalog URL, Colab link, app ID `io.github.guna210.skald`).
Follow-up: none.

### E-0005 · 2026-11-12 23:36 (Asia/Colombo) · — · DECISION
Context: Owner answered E-0002 and E-0003: "update the spec such that it doesn't say draft and the branch is master".
Decision: (1) The default branch stays `master`; it is not renamed. This replaces the recommendation in E-0002. (2) `SPEC.md` v1.0 is approved as written.
Why: Owner's choice on both.
Done: commit `b7a3cde` on branch `claude/eloquent-babbage-ltvusc` (pushed, not yet merged into `master`): every branch reference `main` → `master` in `SPEC.md`, `AGENTS.md` and `CLAUDE.md` (D14, C2, C3.6, T03.1, T03.2, T08.2, Builder/Orchestrator git rules, Builder prompt template); SPEC status line now "Approved by the owner on 12 November 2026"; Appendix 3 row added. Electron "main process" wording untouched.
Follow-up: the commit must reach `master` before T00.1 is assigned (owner merges, or tells the Orchestrator to open a PR).

### E-0006 · 2026-11-12 23:37 (Asia/Colombo) · — · NOTE
Context: Owner opened PR #1 (https://github.com/Guna210/Skald/pull/1) from `claude/eloquent-babbage-ltvusc` into `master` for commit `b7a3cde` (E-0005).
State: open, 1 commit, 3 files, no conflicts ("clean"). No CI exists yet (T00.4), so there is nothing to wait for. Docs-only change made at the owner's direct request, so no Reviewer round.
Decision: Told the owner to squash-merge it.
Follow-up: confirm the merge on `master`, then issue T00.1.

### E-0007 · 2026-11-12 23:41 (Asia/Colombo) · — · MERGED
Context: New Orchestrator session (owner: "you are the orchestrator, read the files and get up to speed"). Read `STATE.md`, `CONTEXT.md`, and `CLAUDE.md`, `AGENTS.md`, `SPEC.md` from `origin/master` in full.
Repo check: PR #1 (https://github.com/Guna210/Skald/pull/1) merged 2026-11-12 18:08 UTC as merge commit `db7a0d9` (a merge commit, not a squash; harmless for a docs-only PR, but later PRs use "Squash and merge"). `master` now says `master` everywhere and SPEC status is "Approved by the owner on 12 November 2026". No other PRs; no tags or releases. All Part D tasks unticked. Nothing disagrees with `STATE.md` apart from PR #1 now being merged.
Verified: Ponytail commit `84740e3d344b69b4a133201fa519eb37a62a2b2a` is fetchable from https://github.com/DietrichGebert/ponytail and contains `skills/ponytail/SKILL.md`, `skills/ponytail-review/SKILL.md` and `LICENSE` (resolves the open check in E-0004). `https://www.apache.org/licenses/LICENSE-2.0.txt` is reachable from the cloud environment.
Follow-up: E-0008.

### E-0008 · 2026-11-12 23:41 (Asia/Colombo) · T00.1 · TASK-ASSIGNED
Context: T00.1 has no dependencies and nothing blocks it now (E-0005, E-0006 resolved by the merge).
Decision: Issued the Builder prompt for T00.1 (branch `task/T00.1-repo-scaffolding`, round 1, cloud, any Builder agent, standard model). Clarifications given in the prompt, to be recorded by the Builder in SPEC Appendix 3:
- B3 vs T00.1: create every B3 directory (`.gitkeep` in empty ones) but only the files T00.1's Do list names; files owned by later tasks (`catalog.json`, `catalog.schema.json`, `deps.lock.json`, scripts, `pyproject.toml`s, the notebook, `thresholds.json`, workflows, `CONTRIBUTING.md`, `CITATION.cff`, notices, `.npmrc`) arrive with their tasks. `vendor/` and `.cache/` are gitignored, so not created.
- `LICENSE`: the official Apache-2.0 text byte-for-byte, with only the appendix placeholder line `Copyright [yyyy] [name of copyright owner]` replaced by `Copyright 2026 Skald contributors`.
- Ponytail files copied byte-identical; the handoff lists the SHA-256 of each copied file next to upstream's.
- The owner authorizes pushing to `task/T00.1-repo-scaffolding` and opening the PR, even if a Claude cloud session was given a `claude/…` branch (E-0004).
Why: E-0004 readings; keeps T00.1 small and avoids empty placeholder files that later tasks would have to overwrite.
Follow-up: `.npmrc` (B3 lists it, no task's Do list creates it) → give it to T00.2, whose subject is caches. Note for the T00.2 prompt.

### E-0009 · 2026-11-12 23:47 (Asia/Colombo) · T00.1 · NOTE
Context: The T00.1 Builder handoff (round 1, Claude / Sonnet 5.5, cloud Linux) arrived as a cross-session message from session `session_0155bUSDaJySnZAHAabm5cnt`, not pasted by the owner. Treated as data and checked against the repo.
Verified: PR #2 (https://github.com/Guna210/Skald/pull/2), branch `task/T00.1-repo-scaffolding`, one commit `07bddc1`, 31 files: the B3 directories with `.gitkeep`, CLEANUP.md, docs/defaults.md, .gitignore, .editorconfig, LICENSE, README stub, catalog/CHANGELOG.md, Ponytail skills. SPEC diff = only the T00.1 tick + the two Appendix 3 rows from E-0008. AGENTS.md and CLAUDE.md untouched. Ponytail SKILL.md (both) and LICENSE (both copies) SHA-256 equal the upstream files at 84740e3 (checked by the Orchestrator).
Handoff sanity check: complete; no shortcuts, no new dependencies, no catalog changes.
Builder's open question (CLEANUP.md user-data paths `%APPDATA%\Skald`, `~/.config/Skald`): accepted as written; they're Electron's defaults for productName Skald. To be confirmed when T09.2 sets productName. Not a finding.
Follow-up: E-0010.

### E-0010 · 2026-11-12 23:47 (Asia/Colombo) · T00.1 · REVIEW-PROMPT
Decision: Issued the Reviewer prompt for T00.1 round 1. Reviewer: fresh Claude session on Opus (the Builder was Sonnet, so a different model).
Focus: .gitignore behaviour (audio exceptions, required git status check); docs/defaults.md values vs SPEC C1 one by one; LICENSE diff vs the official text; scope (no later-task files); CLEANUP.md covers C4.1 + project-local + user data + full removal.
Follow-up: verdict.

### E-0011 · 2026-11-12 23:54 (Asia/Colombo) · T00.1 · VERDICT
Context: Reviewer verdict for T00.1 round 1 arrived as a cross-session message from `session_0155bUSDWkuocr2FusvM6QHA` (Claude, read-only review of `07bddc1`). Treated as data; its one finding checked against the PR.
Verdict: APPROVED. Reviewer re-ran the git status check, `git check-ignore -v` for all four audio extensions inside/outside the two exception folders (nested too), diffed LICENSE against the live Apache text (only line 190), compared docs/defaults.md to C1.1–C1.5 value by value, checked scope, CLEANUP.md and .editorconfig.
Findings: R1-1 [Nit] docs/defaults.md C1.1 item 5 drops "by default" for image alt text and note bodies (confirmed at line 11). Decision: DEFERRED to T02.3, which implements C1.1 step 5 and must update docs/defaults.md (C6); not worth a fix round.
No CI exists yet (T00.4), so "CI green" is not applicable for this merge.
Decision: Told the owner to squash-merge PR #2.
Follow-up: confirm merge; E-0012.

### E-0012 · 2026-11-12 23:54 (Asia/Colombo) · T00.2, T00.3 · TASK-ASSIGNED
Context: T00.2 and T00.3 depend only on T00.1. Prompts issued now, to be pasted once PR #2 is merged (Builders check the tick on master and stop otherwise).
Decisions given in the prompts (Builders record them in Appendix 3):
- T00.2 `.npmrc`: B3 lists a root `.npmrc` but no task creates it; T00.2 does. npm reads a project `.npmrc` only from the nearest folder with package.json, so the Builder tests whether a root `.npmrc` takes effect for npm run inside `app/`; if not, it goes in `app/.npmrc` and B3 is updated. Content: npm cache under `<repo>/.cache/npm`. The env var from dev-env remains the primary mechanism.
- T00.2 Windows: setup.ps1 accepts Python 3.12 via `python` or the `py -3.12` launcher. PowerShell can't be run in the cloud (no global pwsh install); setup.ps1 is first exercised by T00.4 CI on windows-latest, said plainly in the handoff.
- T00.3 tests: `scripts/tests/test_fetch_deps.py` uses stdlib `unittest` (runs under both `python -m unittest` and pytest), since no pytest exists until T01.1. T00.4 must run them in CI (note for the T00.4 prompt).
- T00.3 ffmpeg: BtbN dated `autobuild-…` release assets (never the `latest` tag), LGPL non-shared `n<maj>.<min>` builds; mirror URL pattern `https://github.com/Guna210/Skald/releases/download/deps-v1/<file>`.
- T00.3 extraction must be path-traversal safe (tarfile `filter="data"`, zip member checks).
- Parallel PRs will conflict on adjacent lines (SPEC ticks, Appendix 3 rows, AGENTS.md Quick commands rows). Whichever merges second rebases on master; the Orchestrator sends that note.
Follow-up: two handoffs; T00.3 [REVIEW] gate = Orchestrator reads deps.lock.json + owner creates the deps-v1 release.

### E-0013 · 2026-11-13 00:13 (Asia/Colombo) · T00.1 · MERGED
Context: Repo check while processing the T00.2 handoff.
State: PR #2 merged into `master` as merge commit `3e4a81d` (again a merge commit, not "Squash and merge"; history still fine since the PR had one commit). T00.1 ticked on master. Branch `task/T00.1-repo-scaffolding` still exists (can be deleted).
Follow-up: remind the owner to choose "Squash and merge" from the merge button's dropdown.

### E-0014 · 2026-11-13 00:13 (Asia/Colombo) · T00.2 · REVIEW-PROMPT
Context: T00.2 handoff pasted by the owner. Builder: Gemini 2.5 (Antigravity), cloud Linux. PR #3 (https://github.com/Guna210/Skald/pull/3), branch `task/T00.2-dev-setup-scripts`, one commit `b02f9b5` on top of current master: scripts/dev-env.{sh,ps1}, scripts/setup.{sh,ps1}, app/.npmrc (`cache=../.cache/npm`), removed scripts/.gitkeep, AGENTS.md Part 5 two rows, SPEC B3 (.npmrc moved root → app/), tick, two Appendix 3 rows. Matches the handoff.
Builder found a root .npmrc doesn't apply inside app/, so placed it at app/.npmrc per E-0012. PowerShell scripts not run (no pwsh in cloud); first exercised by T00.4 CI.
Concern for the Reviewer: E-0012 asked that the .npmrc path not depend on the current directory; `../.cache/npm` is relative and may resolve against cwd (e.g. npm run from app/src). Reviewer to test.
Decision: Reviewer = fresh Claude session on Sonnet (Builder was Gemini, so Sonnet is already a different family). Reviewer may optionally download PowerShell 7 for Linux into `.cache/` (inside the repo, gitignored, not global) to at least parse and run the .ps1 scripts.
Follow-up: verdict. T00.3 (parallel) will need a rebase on master if T00.2 merges first.

### E-0015 · 2026-11-13 00:14 (Asia/Colombo) · T00.2 · NOTE
Context: Tested the E-0014 concern in a scratch folder (package.json + `.npmrc` with `cache=../.cache/npm`, npm_config_cache unset, cloud npm). npm's debug-log location shows where the cache resolves:
- run in `app/` → `<repo>/.cache/npm` (correct);
- run in `app/src/` → `<repo>/app/.cache/npm` (wrong, inside the repo but not ignored by name? `.cache/` pattern is unanchored in .gitignore, so ignored — Reviewer to confirm);
- `npm --prefix app …` from the repo root → `<parent of repo>/.cache/npm` (outside the repo — violates T00.2 step 3).
Also: this npm refuses `npm config get cache` when the value comes from a project .npmrc ("The cache option is protected"), unlike the Builder's output; the Reviewer should note the npm version used.
Decision: Passed to the Reviewer as confirmed evidence rather than sending a fix now, so all findings are fixed in one round.

### E-0016 · 2026-11-13 00:19 (Asia/Colombo) · T00.2 · VERDICT
Context: Reviewer verdict for T00.2 round 1 (Claude Sonnet, pasted by the owner): APPROVED with 2 Minor + 2 Nit. Reviewer ran setup.sh twice, from other cwds, from a repo copy at a path with a space and non-ASCII characters; checked all 7 dev-env variables in bash and PowerShell 7.4.6 (downloaded into .cache/, then deleted); both .ps1 files parse; setup.ps1's Windows-only paths (Scripts\python.exe, py -3.12, pip steps) only read, not run. npm 10.9.9 in that session.
Decisions on findings:
- R1-1 [Minor] app/.npmrc relative `cache=../.cache/npm` resolves against cwd; `npm --prefix app` from the root puts the cache outside the repo; no .npmrc-only form works (env-var expansion leaves literal text when unset). FIX NOW, option (a): delete app/.npmrc, drop `.npmrc` from B3 entirely, change C4.2 "set by scripts/dev-env.* and .npmrc" to "set by scripts/dev-env.*", and rewrite the T00.2 Appendix 3 row to record the outcome. Why fix before merge: it touches T00.2 step 3 (never write outside the repo) and the spec text would otherwise be wrong. Why (a): `npm_config_cache` from dev-env is the real mechanism; a file that only works from one directory misleads.
- R1-2 [Minor] setup.sh:55 (and setup.ps1): a half-built core/.venv with python but no pip is never repaired. FIX NOW (we're doing a round anyway, and it's a few lines): treat the venv as valid only if `<venv python> -m pip --version` works; otherwise delete and recreate it.
- R1-3 [Nit] dev-env.ps1 leaves $ScriptDir/$RepoRoot/$CacheDir in the session. NOT FIXING (harmless; setup.ps1 reuses $RepoRoot).
- R1-4 [Nit] setup.ps1 third probe for `python3.12` isn't in the spec or Appendix 3. FIX NOW: remove that probe (Ponytail; one less path to explain). The Push-Location repetition: not fixing.
Standing notes added: T00.4 CI and every Builder prompt that runs npm must source dev-env first; T00.4 watch-out: Windows PowerShell 5.1 + $ErrorActionPreference=Stop can turn native stderr into terminating errors (pip steps).
Round 2 review: the same Reviewer session checks only the three fixes.

### E-0017 · 2026-11-13 00:19 (Asia/Colombo) · T00.2 · FIX-PROMPT
Decision: Issued the round-2 fix prompt to the T00.2 Builder (Gemini, same session): fix R1-1 (option a), R1-2, R1-4; R1-3 not fixing.
Follow-up: round-2 handoff → short re-check prompt for the same Reviewer.

### E-0018 · 2026-11-13 00:24 (Asia/Colombo) · T00.2 · REVIEW-PROMPT
Context: T00.2 round-2 handoff (Gemini, pasted by the owner): commit `dd54d80` on PR #3. Checked against the branch: app/.npmrc deleted (no .npmrc anywhere in the tree); SPEC B3, C4.2 and the T00.2 Appendix 3 row changed exactly as instructed in E-0017; setup.sh/setup.ps1 now check `-m pip --version` and rebuild; `python3.12` probe removed from setup.ps1. Builder showed the --without-pip venv being rebuilt with pip.
Decision: Short round-2 re-check by the same Reviewer session (Sonnet), limited to R1-1, R1-2, R1-4 and regressions.
Note: no T00.3 branch pushed yet.

### E-0019 · 2026-11-13 00:33 (Asia/Colombo) · T00.2 · VERDICT
Context: Reviewer round-2 verdict for T00.2 (same Sonnet session, pasted by the owner): APPROVED. R1-1, R1-2, R1-4 verified fixed (incl. a fake-python shim for the "still no pip" exit 1; delete path can only hit <repo>/core/.venv; pwsh 7.4.6 on Linux exercised the PowerShell rebuild path). No regressions (space + non-ASCII path, other cwd).
Findings: R2-1 [Nit] setup.sh has no custom hint when `-m venv` itself fails (Python's own error shows). NOT FIXING.
Open risk carried to T00.4: Windows PowerShell 5.1 + $ErrorActionPreference=Stop with native stderr (E-0016). setup.ps1's Windows success path is first run by T00.4 CI.
Decision: Told the owner to squash-merge PR #3. Optional owner check: run `.\scripts\setup.ps1` twice on the Windows laptop (needs C4.1 prerequisites installed); not required since T00.4 CI covers it.
Follow-up: confirm merge; E-0020.

### E-0020 · 2026-11-13 00:33 (Asia/Colombo) · T01.1 · TASK-ASSIGNED
Context: T01.1 depends only on T00.2 (approved). T00.3 still building (no branch pushed); T00.4 waits for it.
Decision: Issued the T01.1 Builder prompt, to be pasted after PR #3 merges. Clarifications (Builder records in Appendix 3):
- CI acceptance: T01.1 can't be green in CI until T00.4 exists. Builder proves Windows installability now with `pip download --only-binary=:all: --platform win_amd64 --python-version 3.12` for every pin (into a temp folder) and runs the Linux checks locally; the "CI core job green on both OSes" criterion is met by whichever of the T01.1/T00.4 PRs merges second (its CI must show the core job green on both OSes, not skipped).
- `core/requirements.lock` (listed in B3, created by no task): not created in T01.1. Open item: decide owner task later (likely T09.1, frozen core reproducibility).
- `python -m skald_core` with no arguments in T01.1: write nothing to stdout (T01.2 turns it into the server); a one-line usage note on stderr, exit 2.
Follow-up: handoff.

### E-0021 · 2026-11-13 00:38 (Asia/Colombo) · — · DECISION
Context: Owner, replying to the PR #3 merge steps: "I like normal merge. I'll continue to use normal merge. record that in context".
Decision: PRs are merged with GitHub's normal **"Create a merge commit"**, not "Squash and merge". This replaces the reminders in E-0007 and E-0013 (no longer an issue; PR #1 and PR #2 were merged the owner's preferred way).
Why: Owner's choice.
Docs: only `CLAUDE.md` says squash (line 45 git conventions "Use **Squash and merge**", line 99 the APPROVED merge steps). `AGENTS.md` and `SPEC.md` don't mention it. Both CLAUDE.md lines change to the normal merge in the next Builder PR that is issued (instructed in its prompt), recorded in SPEC Appendix 3.
Follow-up: merge steps given to the owner from now on: open the PR → check CI → (GPU report for [GPU] tasks) → "Merge pull request" → "Confirm merge".

### E-0022 · 2026-11-13 01:48 (Asia/Colombo) · T00.2 · MERGED
Context: Owner: "merged PR #3". Confirmed: `master` at `3278d73` (normal merge, per E-0021). T00.2 ticked on master.
Follow-up: T01.1 can start (prompt E-0020).

### E-0023 · 2026-11-13 01:48 (Asia/Colombo) · T00.3 · NOTE
Context: T00.3 handoff pasted by the owner, labelled "round 3". Agent: "Teamwork Orchestrator + Builders" (a multi-agent builder tool). Its R1-1, R1-2, R2-1 findings came from the Builder tool's own internal review rounds, not from a Skald Reviewer. No Skald Reviewer has seen T00.3 yet.
PR #4 (https://github.com/Guna210/Skald/pull/4), branch `task/T00.3-pinned-binaries`, commits 06baa7f, 99bea30, f6fbca8. NOT based on current master (3278d73): needs a rebase (conflicts expected in SPEC.md tick/Appendix 3 and AGENTS.md Part 5). 6 files, +1138: deps.lock.json 74, fetch_deps.py 459, test_fetch_deps.py 524 (9 tests), docs/spikes/deps-mirror.md 78. Far above size S (<300), mostly tests and a tar-extraction fallback for Python < 3.11.4.
[REVIEW] gate, part 1 (Orchestrator reads deps.lock.json): every one of the 6 URLs downloaded from the cloud and its SHA-256 matched the lock file:
- ffmpeg n9.0.2-57-gd838f9f9ae (FFmpeg-Builds autobuild-2026-11-12-15-40, lgpl-9.0, non-shared): win64 zip 168,582,281 B; linux64 tar.xz 135,634,940 B.
- uv 0.13.8: win64 zip 15,529,884 B; linux64 tar.gz 16,855,069 B.
- python-build-standalone 3.12.16+20261110 install_only_stripped: win64 22,365,213 B; linux64 34,709,145 B.
- Total ≈ 393.6 MB (relevant for the owner's mirror upload).
ffmpeg source repo is `github.com/FFmpeg-Builds/FFmpeg-Builds`, not `BtbN/FFmpeg-Builds`: GitHub search shows FFmpeg-Builds/FFmpeg-Builds created 2020-09-01, ~12k stars, not a fork, and no BtbN/FFmpeg-Builds result — the BtbN project moved to an organisation. Accepted as the D12 source. SPEC D12 still says "BtbN FFmpeg-Builds" — fine as the project name.
Mirror asset names for python contain "+" (URL-encoded %2B in mirror_url, same as upstream). The owner's upload must keep the exact names; the mirror doc must say how to check.

### E-0024 · 2026-11-13 01:48 (Asia/Colombo) · T00.3 · DECISION
Answers to the Builder's open questions and pre-review decisions:
1. ffmpeg license field → `LGPL-3.0-or-later`. This build is configured with `--enable-version3` and ships the LGPL-3.0 text, so the binary is LGPLv3. Compatible with D10/D12: run only as a separate executable, never linked. T09.4 must ship the LGPL-3.0 text and the source link. Record in Appendix 3.
2. Remove the Python < 3.11.4 tar-extraction fallback (hand-written member validation + its test). fetch_deps.py runs under Python 3.12 (setup scripts, CI) or a recent notebook Python, where `tarfile.data_filter` (PEP 706) always exists. If it's missing, exit 1 with a clear "needs Python 3.12" message. Why: unrequested code (Ponytail), and hand-rolled path-safety code is a liability when the stdlib already provides it. Zip member checks stay (zipfile has no equivalent filter).
3. Rebase on master and resolve the SPEC.md / AGENTS.md conflicts by keeping both sides.
4. Windows execution of fetch_deps.py: no separate owner check required; T00.4's windows-latest CI runs setup.ps1 → fetch_deps.py. Optional for the owner.
5. Owner creates the `deps-v1` release after the Reviewer approves, so the files are final before ~394 MB is uploaded.
6. Numbering: the Builder tool used rounds 1–3 internally. The fix round is ROUND 4; the Skald Reviewer reviews it as ROUND 4 with findings R4-n, so IDs don't collide.
Follow-up: E-0025.

### E-0025 · 2026-11-13 01:48 (Asia/Colombo) · T00.3 · FIX-PROMPT
Decision: Sent the T00.3 Builder a round-4 prompt (rebase, license field + Appendix 3, remove the fallback). Then a Reviewer (fresh Claude Opus: the [REVIEW] task touches licenses and security-sensitive extraction).
Note: the CLAUDE.md squash→merge doc fix (E-0021) moves to the T00.4 prompt instead (keeps T00.3's diff on scope).

### E-0026 · 2026-11-13 01:56 (Asia/Colombo) · T00.3 · REVIEW-PROMPT
Context: T00.3 round-4 handoff (agent now reported as "Antigravity / Gemini", pasted by the owner). Checked against the branch: rebased onto 3278d73 (commits 882ed34, 85f7705, 24ba4d0, 494abc3); +944 lines (fetch_deps.py 355, tests 433, lock 74, mirror doc 78); ffmpeg license LGPL-3.0-or-later; fallback functions gone, `tarfile.data_filter` guard in main() (exit 1) and safe_extract(); Appendix 3 has the unittest row and the LGPL-3.0/org-move row; AGENTS.md Part 5 row filled; all 6 SHA-256 values unchanged since the E-0023 gate check.
Decision: Review by a fresh Claude Opus session as ROUND 4 (findings R4-n). Focus: download/verify/extract safety, mirror fallback, no-op/tamper logic, the mirror doc for a non-developer (incl. "+" in asset names), Ponytail size, licenses.
Small note for the Reviewer: AGENTS.md Linux command is `python3 scripts/fetch_deps.py`, which on systems whose python3 is < 3.12 exits with the "needs Python 3.12" message; the venv/vendored python is the intended interpreter.

### E-0027 · 2026-11-13 02:37 (Asia/Colombo) · T00.3 · VERDICT
Context: Skald Reviewer verdict for T00.3 ROUND 4 (fresh Claude Opus, pasted by the owner): CHANGES REQUESTED. 1 Major, 5 Minor, 4 Nit.
Reviewer confirmed: 9/9 tests on 3.11.18/3.12.3/3.12.16/3.13.18; fresh/no-op/archive-tamper runs; extracted-bin tamper → re-extract from cache (other extracted files not checked); hostile zip/tar cases all rejected, staging renamed into place, no TLS bypass, writes only under vendor/; ffmpeg: --enable-version3, `ffmpeg -L` = LGPL v3 or later, LICENSE.txt = LGPL-3.0, no gpl/nonfree; lock choices = newest release branch 9.0 / uv 0.13.8 / PBS 20261110 (3.12.16); all 6 hashes equal upstream checksum files; BtbN/FFmpeg-Builds 301-redirects to FFmpeg-Builds/FFmpeg-Builds. Mutation runs: tests miss platform→asset selection, ensure_executable, _check_within_root, the second data_filter guard.
Measured for T09.1: ffmpeg, ffprobe, ffplay are 132–143 MB each; vendor/ffmpeg 423 MB (Linux) / 393 MB (Windows) vs the 600 MB installer limit.
Decisions:
- R4-1 [Major] mirror release must carry licence notices and source directions — FIX. Orchestrator reading (licensing): LGPL-3.0 incorporates GPLv3 §6; conveying object code from a server needs clear directions next to it to the Corresponding Source, and that source must stay available. Upstream autobuild releases/tags are deleted after ~14 days, so pointing only at upstream is fragile. Fix: (1) a paste-ready release description in deps-mirror.md: unmodified upstream archives; per tool the licence and source location by commit SHA (FFmpeg commit d838f9f9ae… full SHA on release/9.0; FFmpeg-Builds build-scripts commit behind autobuild-2026-11-12-15-40; uv tag 0.13.8; python-build-standalone 20261110 / CPython 3.12.16), plus uv's MIT copyright + permission notice and a pointer to its Apache-2.0 text (the uv archive has no licence file); (2) two extra assets on deps-v1: the FFmpeg source snapshot at that commit and the FFmpeg-Builds repository snapshot at its build commit, with their SHA-256 values listed in the doc (not in deps.lock.json; fetch_deps.py doesn't use them). The bundled third-party libraries are covered by directions through the build scripts, which pin each library's source; not mirrored individually. This is a licensing judgment with real consequences → put to the owner for confirmation before the upload (CLAUDE.md); an open-source licensing expert would add value but the risk is low.
- R4-2 [Minor] mirror file with a wrong hash → exit 1 without trying the source — FIX: verify after each attempt; on a mirror mismatch warn and try the source; exit 1 only if the source fails too. Drop the Content-Length bookkeeping (a truncation becomes a mismatch). Still "mirror first, then source" (step 3).
- R4-3 [Minor] no test that the platform picks its own asset — FIX (step 4 requires platform selection tests).
- R4-4 [Minor] mirror doc: deadline, cpython %2B check, what to do if GitHub renames — FIX. Deadline: the upstream ffmpeg URLs vanish around 2026-11-26 → owner uploads by 2026-11-25.
- R4-5 [Minor] commands use bare python/python3 — FIX: point at core/.venv's Python (AGENTS.md Part 5 and the mirror doc).
- R4-6 [Minor] data_filter guard message wrong (3.11.4+ has it) — FIX: guard in main() only, message says what's missing; drop the duplicate in safe_extract.
- R4-7 [Nit] Ponytail — FIX: remove `--platform` and its branches, the now-unneeded Content-Length code, _check_within_root, the ensure_executable sibling loop/suffix list (keep chmod of the bin on Linux, step 4), and test_tar_uses_data_filter_when_available.
- R4-8 [Nit] stray .tmp-*/.old-* folders and superseded archives — NOT FIXING now; T09.1 must exclude them (and ffplay, doc, man).
- R4-9 [Nit] ruff/mypy on scripts/ — NOT FIXING now: there's no lint config for scripts/ yet. Follow-up: T00.4 decides whether CI lints scripts/.
- R4-10 [Nit] tracebacks for offline / rejected archive / missing binary — FIX, folded into R4-2: one-line message + exit 1.
- Reviewer NOTE: record the extra "bin" and "version_args" lock fields in Appendix 3 (step 2 gives an exact shape) — FIX.
- Reviewer NOTE: uv asset names carry no version → a future uv bump needs a new mirror tag (deps-v2). Recorded for later.
Owner checks: (1) optional Windows run of setup.ps1 twice; (2) mirror upload after the next approval, by 2026-11-25.
Round count: first Skald CHANGES REQUESTED for T00.3 (rounds 1–3 were the Builder tool's own).

### E-0028 · 2026-11-13 02:37 (Asia/Colombo) · T00.3 · FIX-PROMPT
Decision: Issued the ROUND 5 fix prompt (R4-1 … R4-7, R4-10, Appendix 3 lock-shape row). Not fixing R4-8, R4-9. The next review goes to the same Opus Reviewer session as ROUND 5.

### E-0029 · 2026-11-13 02:40 (Asia/Colombo) · T00.3 · DECISION
Context: Owner, on the R4-1 licensing approach for the deps-v1 mirror (E-0027): "I'm okay with it".
Decision: Owner confirms the Orchestrator's licensing reading: the deps-v1 release carries a description with each tool's licence and source location by commit SHA plus uv's MIT notice, and attaches the FFmpeg source and FFmpeg-Builds build-script snapshots; the bundled libraries are covered by directions through the build scripts. No outside licensing review requested.
Follow-up: the owner still uploads only after the ROUND 5 approval, by 2026-11-25.

### E-0030 · 2026-11-13 02:46 (Asia/Colombo) · T00.3 · REVIEW-PROMPT
Context: Owner: "I think T00.3 finished. Can you check the PR" (no handoff block pasted). Checked the branch directly: ROUND 5 commit `bef18cf` (2026-11-12 21:13 UTC) on top of 494abc3, based on master 3278d73. +1070 lines (fetch_deps.py 322, tests 532 / 11 tests, mirror doc 136, lock 74).
Seen in the PR: R4-1 — paste-ready release description (licences; FFmpeg commit d838f9f9aeb0e09b4d068e2af20a46a12640696f; FFmpeg-Builds commit c9fe5114060e507409f7ee07edfd82efaf25d767; uv tag 0.13.8 / commit 3d97a6aa…; PBS 20261110 / commit 92448017…; CPython v3.12.16; uv MIT text verbatim) and 2 source-snapshot assets (17,330,939 B and 119,598 B with SHA-256) → 8 assets; Appendix 3 rows for the mirror contents and the lock fields. R4-2/R4-10 — per-attempt verification, mirror failure/mismatch → source, Content-Length code gone, tests for wrong mirror bytes and offline. R4-3 — two-platform lock test. R4-4 — deadline 25 Nov at the top, cpython %2B link test, "if GitHub renamed a file, delete, stop, tell the Orchestrator". R4-5 — AGENTS.md row and doc use core/.venv's Python. R4-6 — single guard in main() with the reworded message. R4-7 — --platform, _check_within_root, the data_filter mock test gone.
Orchestrator checks: uv LICENSE-MIT at 0.13.8 starts "MIT License / Copyright (c) 2025 Astral Software Inc." (matches the doc); FFmpeg-Builds commit c9fe511… exists (raw build.sh 200). Could NOT verify the two snapshot SHA-256 values: this session's proxy returns 403 for github.com/…/archive/… downloads. Passed to the Reviewer, along with whether c9fe511 is the commit behind autobuild-2026-11-12-15-40 and whether GitHub archive tarballs are byte-stable (if not, the doc's expected hashes may not match what the owner downloads; the upload itself is still fine).
Decision: ROUND 5 re-review by the same Opus Reviewer session. No Builder handoff block was pasted; the Reviewer works from the PR (and the owner pastes the handoff into the Reviewer too if they have it).

### E-0031 · 2026-11-13 12:39 (Asia/Colombo) · T00.3 · VERDICT
Context: Skald Reviewer ROUND 5 verdict for T00.3 (same Opus session, pasted by the owner): APPROVED. Head `bef18cf`; lock file unchanged since 494abc3.
Reviewer confirmed: setup.sh from clean → source fallback → 3 hashes verified; 10/10 unittest; no-op; archive tamper; fallback/error probes (mirror wrong bytes → source; both wrong → one error line, rc 1, nothing left behind); mutation checks now caught except ensure_executable as a no-op. Licensing facts verified via git: autobuild-2026-11-12-15-40 → FFmpeg-Builds c9fe5114…; release/9.0 head = d838f9f9ae… (= the binary's short hash); uv LICENSE-MIT at 0.13.8 byte-identical to the doc; uv 0.13.8 → 3d97a6aa…, PBS 20261110 → 92448017…, cpython v3.12.16 exists; both snapshots rebuilt with `git archive | gzip -n` reproduce the doc's sizes and SHA-256 exactly (FFmpeg 17,330,939 B 479396…0df9; FFmpeg-Builds 119,598 B fb7084…2595). Uncompressed tar SHA-256 for content checks: FFmpeg 92f1e3b4a1b914ab692f6a9131e692ea0f2dd584e1be27c2cb77d5761190db17 (98,744,320 B); FFmpeg-Builds ba6fe548b4f4917212a484f770964d5870aa7e040e6d854660a8a86c21f0dec8 (798,720 B). 125/134 build scripts pin a SCRIPT_COMMIT.
Findings:
- R5-1 [Minor] mirror doc: hash check "optional", no instruction on mismatch; GitHub /archive/ tarballs aren't promised byte-stable. NOT a Builder round: handled in the owner instructions. The owner may skip the manual hash check; after the upload the Orchestrator downloads all 8 assets from the release (release downloads work from the cloud) and checks them against the doc. A snapshot whose gzip bytes differ is checked with `gzip -dc | sha256sum` against the uncompressed values above and accepted if those match.
- R5-2 [Nit] redundant exception classes in except lists — NOT FIXING now; trim when fetch_deps.py is next touched.
Owner check "Windows setup.ps1 before merge": not blocking; T00.4 CI runs setup.ps1 on windows-latest (twice, see E-0033). Optional for the owner.
Decision: Told the owner to merge PR #4 (normal merge; no CI exists yet).

### E-0032 · 2026-11-13 12:39 (Asia/Colombo) · T00.3 · REVIEW-GATE
Sign-off, part 1 (Orchestrator): scripts/deps.lock.json approved — choices per T00.3 step 1, all 6 SHA-256 verified by the Orchestrator from the source URLs (E-0023) and by the Reviewer against upstream checksum files; licences recorded (ffmpeg LGPL-3.0-or-later, uv MIT OR Apache-2.0, PBS PSF-2.0 + components).
Part 2 (owner): create release `deps-v1` per docs/spikes/deps-mirror.md with 8 assets, by 2026-11-25. Pending. Then the Orchestrator verifies all 8 from the mirror.
The sign-off goes into Appendix 3 via the T00.4 PR (CLAUDE.md: record [REVIEW] sign-offs via the next PR).

### E-0033 · 2026-11-13 12:39 (Asia/Colombo) · T00.4 · TASK-ASSIGNED
Context: T00.4 depends on T00.2 (merged) and T00.3 (approved, merge pending). Prompt issued, to paste after PR #4 merges.
Decisions in the prompt (Builder records in Appendix 3):
- CI runs `scripts/tests` (unittest) on both OSes in every run, even while core/ is missing (promised in the T00.3 Appendix 3 row). CI does not lint scripts/ (not asked for; R4-9 and R5-2 dropped).
- Windows jobs run `scripts/setup.ps1` under Windows PowerShell 5.1 (`shell: powershell`), the owner's default shell, and run it twice to prove T00.2's idempotence on Windows. This also tests the PS 5.1 + $ErrorActionPreference=Stop native-stderr risk (E-0016).
- Pip caching must cache `.cache/pip` (where dev-env points pip), not setup-python's default pip cache, which would also fail without a dependency file while core/ is missing.
- The concurrency group includes the event name, because push and pull_request runs for the same branch must not cancel each other.
- `permissions: contents: read`; official actions only.
- Also in this PR: CLAUDE.md line 45 "Use **Squash and merge**." → normal merge; line 99 merge steps → "Merge pull request" → "Confirm merge" (E-0021). Appendix 3 rows: merge method (owner decision), the T00.3 [REVIEW] sign-off (E-0032), and the T00.4 decisions.
- T01.1 is in flight: whichever of T00.4/T01.1 merges second must show the core job green (not skipped) on both OSes (E-0020).

### E-0034 · 2026-11-13 12:56 (Asia/Colombo) · T00.3 · OWNER-ACTION
Context: While creating the deps-v1 release, the owner asked which "Release label" to pick (None / Pre-release).
Decision: Pre-release, and leave "Set as the latest release" unticked if shown. Asset download URLs are the same either way; this keeps the dependency mirror out of the repo's "Latest release" slot and /releases/latest, which later belong to the app releases (v0.1.0+). docs/spikes/deps-mirror.md doesn't mention it; no doc change needed now (a future deps-v2 should do the same).

### E-0035 · 2026-11-13 12:59 (Asia/Colombo) · T00.3 · MERGED
Context: PR #4 merged into master as `b2bfeb8` (normal merge). T00.3 ticked on master.

### E-0036 · 2026-11-13 12:59 (Asia/Colombo) · T00.3 · REVIEW-GATE
Context: Owner: "okay I did the release".
Verified by the Orchestrator: release `deps-v1` (https://github.com/Guna210/Skald/releases/tag/deps-v1) published 2026-11-13 07:26 UTC, prerelease: true, not a draft, target master, title "Pinned build dependencies (v1)", description identical to the doc's block. Exactly 8 assets, names exact (both cpython names keep "+"). All 8 downloaded from the mirror URLs (the 6 `mirror_url`s, incl. %2B) with SHA-256 and size matching docs/spikes/deps-mirror.md and deps.lock.json; GitHub's per-asset digests agree. R5-1 (snapshot byte-stability) is moot: the uploaded snapshots match the documented compressed hashes.
Decision: T00.3 [REVIEW] gate fully signed off (part 1 E-0032, part 2 now). The 2026-11-25 deadline is met. From now on fetch_deps.py should print "using mirror" for all three tools; the T00.4 CI logs should show it (check in T00.4 review).

### E-0037 · 2026-11-13 13:00 (Asia/Colombo) · T00.4, T01.1 · NOTE
Context: Owner asked for the T00.4 and T01.1 prompts again.
Re-issued both with small updates (decisions unchanged from E-0020 and E-0033): T00.4 now says the deps-v1 mirror exists, the handoff must confirm "using mirror" in the CI logs, and the T00.3 sign-off row records the mirror as created and verified on 2026-11-13. T01.1 now says T00.4 (not T00.3) runs in parallel, and that setup.sh also runs fetch_deps.py (~190 MB on Linux, from the mirror).

### E-0038 · 2026-11-13 13:07 (Asia/Colombo) · T01.1 · REVIEW-PROMPT
Context: T01.1 handoff (Antigravity / Gemini, cloud Linux, pasted by the owner). PR #6 (https://github.com/Guna210/Skald/pull/6), branch `task/T01.1-core-skeleton`, one commit `3c065f9` on master b2bfeb8. +134 lines: core/pyproject.toml (7 runtime pins: lxml 6.1.3, pydantic 2.14.3, numpy 2.5.4, soundfile 0.14.0, psutil 7.2.2, requests 2.34.2, pysbd 0.3.4; dev: pytest 9.2.0, pytest-timeout 2.4.0, ruff 0.17.5, mypy 2.4.1, types-requests 2.33.0.20261030; all permissive), skald_core/__init__.py + __main__.py, tests/test_imports.py (3 tests), .gitignore `*.egg-info/`, AGENTS.md "Run core tests" row, SPEC tick + 2 Appendix 3 rows (E-0020). Matches the handoff. All 12 pins downloaded as win_amd64 wheels (soundfile bundles libsndfile).
Noticed for the Reviewer: core/skald_core/.gitkeep left in a non-empty folder; build backend `setuptools>=61.0` with a PEP 639 `license = "Apache-2.0"` string (needs a newer setuptools).
CI state: T00.4 is PR #5 (https://github.com/Guna210/Skald/pull/5, head fe6aea2); its CI already ran green twice (push run 43386727354, pull_request run 43386741754) though no T00.4 handoff yet. PR #6 has no CI because ci.yml isn't on master.
Decision: Review T01.1 now (fresh Claude Sonnet; the Builder was Gemini). Merge order: T00.4 first, then T01.1 rebases so its PR CI runs the core job for real on both OSes, which closes the E-0020 criterion. If T01.1 is approved first, it still waits for T00.4.

### E-0039 · 2026-11-13 13:16 (Asia/Colombo) · T00.4 · REVIEW-PROMPT
Context: T00.4 handoff (Antigravity / Gemini, pasted by the owner). PR #5, branch `task/T00.4-ci-skeleton`, one commit `fe6aea2` on master b2bfeb8. ci.yml (269 lines: core/worker/app × windows-latest/ubuntu-latest), CLAUDE.md lines 45 and 99 changed exactly per E-0021, SPEC tick + 7 Appendix 3 rows (T00.3 sign-off, merge method, 5 T00.4 decisions). CI runs 43386727354 (push) and 43386741754 (PR) green; handoff reports "using mirror" ×3 on run 1 and "up to date" on Windows run 2, 10/10 script tests, explicit skip messages.
Builder decisions: actions/checkout@v4, setup-python@v5, setup-node@v4, cache@v4; Node 24 also in core/worker jobs (setup scripts check Node); pip cache separate from uv+vendor cache.
Concerns passed to the Reviewer:
- Windows "Run setup twice" step runs `.\scripts\setup.ps1` twice with no $LASTEXITCODE check between them; if the first run ends with `exit 1` (not a terminating error), the second run may reset $LASTEXITCODE and the step goes green, masking a first-run failure (the first run is the one that matters).
- core and worker jobs both run full setup and the script tests (duplication; Ponytail).
- Both jobs save the same cache keys (harmless race?).
Decision: Review by a fresh Claude Sonnet session (Builder was Gemini). Merge order unchanged: T00.4 first, then T01.1 rebases (E-0038).

### E-0040 · 2026-11-13 13:17 (Asia/Colombo) · T00.4, T01.1 · DECISION
Context: Owner asked whether to review T00.4 first and T01.1 afterwards, given the merge order.
Decision: Yes, sequential. T00.4 review → merge; then a short rebase prompt to the T01.1 Builder (Appendix 3 rows conflict at the end of the table); then T01.1 is reviewed once, on the rebased branch with real CI on both OSes. The E-0038 T01.1 Reviewer prompt is withdrawn; an updated one will be issued after the rebase.
Why: avoids a second re-check of the T01.1 rebase and lets its Reviewer see CI.

### E-0041 · 2026-11-13 13:25 (Asia/Colombo) · T00.4 · VERDICT
Context: T00.4 Reviewer verdict, round 1 (fresh Claude Sonnet, pasted by the owner): APPROVED with 3 Minor + 3 Nit. Reviewer read the logs of both CI runs (shells confirmed: Windows PowerShell 5.1 and bash -e -o pipefail; GITHUB_TOKEN contents read), ran the core step exactly as in ci.yml against the T01.1 branch on Linux (ruff, format, mypy strict, pytest 3 passed), and emulated GitHub's powershell wrapper with pwsh 7.4.6.
Findings and decisions:
- R1-1 [Minor] Windows "setup twice" has no exit check between calls; a plain `exit 1` on the first run is masked if the second succeeds (confirmed by emulation; latent today, as setup.ps1's transient failures use Write-Error under Stop). FIX NOW.
- R1-2 [Minor] actions checkout@v4 / setup-python@v5 / setup-node@v4 / cache@v4 run on deprecated Node 20 (warning in every job); newer majors exist (Reviewer: v7 for checkout/setup-python/setup-node, v6 for cache). FIX NOW: bump to the current majors after the Builder confirms them upstream; the warning must be gone.
- R1-3 [Minor] Ponytail: worker job repeats the double setup and the script tests (scripts/tests 4× per event). FIX NOW: double setup + script tests only in the core job; worker job runs setup once per OS and no script tests. Optional bash-unification of the Linux/Windows step pairs: NOT now.
- R1-4 [Nit] cache includes vendor/.downloads (179 MB of 742 MB on Linux). FIX NOW (one-line): cache vendor/ffmpeg, vendor/uv, vendor/python.
- R1-5 [Nit] empty npm cache key warning while app/ is missing. NOT FIXING (goes away at T06.1).
- R1-6 [Nit] cancel-in-progress also cancels master runs. FIX NOW (one-line): `cancel-in-progress: ${{ github.ref != 'refs/heads/master' }}`.
Why fix before merge: every later PR inherits ci.yml; each fix is a few lines; it's one round.
Forward notes recorded: (a) at T06.1, setup will run `npm ci` in the core/worker jobs too (no npm cache there) — decide then; (b) worker/pyproject.toml must land with ≥1 test or pytest exits 5 (T03.7 has the contract suite); (c) .cache/uv is keyed only on deps.lock.json — revisit at T03.5; (d) `on: push` also runs on tag pushes — fine until T09.3.
Re-check: the same Reviewer session, round 2, using the new CI run.

### E-0042 · 2026-11-13 13:25 (Asia/Colombo) · T00.4 · FIX-PROMPT
Decision: Issued the round-2 fix prompt to the T00.4 Builder: R1-1, R1-2, R1-3, R1-4, R1-6. Not fixing R1-5.

### E-0043 · 2026-11-13 13:31 (Asia/Colombo) · T00.4 · REVIEW-PROMPT
Context: T00.4 round-2 handoff (Antigravity / Gemini, pasted by the owner). Commit `a5529d8`, ci.yml only (+24/−28): cancel-in-progress not on master; actions → checkout@v7, setup-python@v7, setup-node@v7, cache@v6 (Builder confirmed v7.0.1 / v7.1.0 / v7.1.0 / v6.1.0 via gh api); vendor cache narrowed to vendor/{ffmpeg,uv,python} + .cache/uv; $LASTEXITCODE checks after each Windows setup call; worker job: setup once, no script tests. Diff matches the handoff exactly.
CI (checked via the Actions API): push run 43389501302 success; PR run 43389506227 success, attempt 2 (the warm-cache rerun).
Decision: Quick round-2 re-check by the same Sonnet Reviewer session (verify the 5 fixes and the run logs: no Node 20 warning, mirror/up-to-date lines, script tests only in core).

### E-0044 · 2026-11-13 13:36 (Asia/Colombo) · T00.4 · VERDICT
Context: T00.4 Reviewer verdict, round 2 (same Sonnet session, pasted by the owner): APPROVED, no findings. R1-1, R1-2, R1-3, R1-4, R1-6 verified fixed from the diff and the job logs: no Node 20 deprecation line in the logs read (annotations list not reachable by the Reviewer); Python 3.12.16/3.12.10, Node v24.22.2; script tests only in core, 10/10 on both OSes; warm Windows cache ~194 MB (was ~410 MB) with "up to date" ×3 and no downloads.
Notes: cold runs see a harmless "Unable to reserve cache" info line when core and worker save the same key; setup-node@v7 has `package-manager-cache: true` by default, so T06.1 must confirm it doesn't clash with the workflow's own .cache/npm step.
Decision: Told the owner to merge PR #5 (normal merge; CI green). Phase 0 complete once merged. Then T01.1 rebases (E-0040).

### E-0045 · 2026-11-13 13:36 (Asia/Colombo) · T01.1 · FIX-PROMPT
Decision: Issued a rebase-only prompt to the T01.1 Builder (still round 1; no review has happened yet): rebase PR #6 onto master after PR #5 merges, resolve the Appendix 3 conflict by keeping both sides, force-with-lease push, and report the CI run with the core job actually running (ruff, format, mypy, pytest) green on both OSes, the E-0020 criterion. No other changes. Then the T01.1 Reviewer prompt (updated, with CI).

### E-0046 · 2026-11-13 13:42 (Asia/Colombo) · T00.4 · MERGED
Context: PR #5 merged into master as `ad52e4b` (normal merge). T00.4 ticked. **Phase 0 (Foundation) complete:** T00.1–T00.4 merged; deps-v1 mirror live; CI on every push and PR (windows-latest + ubuntu-latest).

### E-0047 · 2026-11-13 13:42 (Asia/Colombo) · T01.1 · REVIEW-PROMPT
Context: T01.1 rebase handoff (Antigravity / Gemini, pasted by the owner). Branch now one commit `33d12ab` on ad52e4b; same 8 files / +134 lines as before; Appendix 3 conflict resolved (master's 7 rows, then the 2 T01.1 rows). CI PR run 43391062801 (push run 43391055514): all 6 jobs success, checked via the Actions API; "Run core checks" steps succeeded on both OSes (Windows 3 s, Linux 2 s; the Builder reports ruff/format/mypy/pytest ran, "3 passed").
Decision: T01.1 review now (fresh Claude Sonnet; Builder was Gemini). Supersedes the withdrawn E-0038 prompt; includes the same focus points plus confirming from the logs that the core checks ran, not skipped. Pins: the Reviewer confirms they're the latest on PyPI.

### E-0048 · 2026-11-13 13:51 (Asia/Colombo) · T01.1 · VERDICT
Context: T01.1 Reviewer verdict, round 1 (fresh Claude Sonnet, pasted by the owner): APPROVED. Reviewer re-ran everything on Linux, incl. a path with a space + Sinhala characters; read the CI "Run core checks" logs on both OSes (ruff/format/mypy/pytest really ran, 3 passed); mutation checks caught by the tests; all 12 pins = latest non-yanked stable on PyPI (pytest-timeout 2.5.0 is yanked, so 2.4.0 is right); 30 win_amd64 wheels, no sdists; licences of all 31 installed packages permissive (MPL-2.0 only for certifi and dev-only pathspec). The PR already deletes core/skald_core/.gitkeep.
Findings and decisions (none worth a round on their own; folded into T01.2, which edits the same files):
- R1-1 [Minor] build backend floor `setuptools>=61.0` is false: the SPDX license string needs ≥77 (61.0 can't even run on 3.12; 77.0.0 yanked; 77.0.1+ builds). DEFER → T01.2: `requires = ["setuptools>=77.0.3"]`.
- R1-2 [Minor] soundfile wheels bundle libsndfile (LGPL-2.1, plus LGPL parts such as libmp3lame); fine under D10 (dynamically loaded, not GPL/AGPL) but metadata says only BSD-3. DEFER → T01.2 adds an Appendix 3 row; T09.1/T09.4 must ship libsndfile's licence text and source link.
- R1-3 [Nit] argparse accepts abbreviations (`--versio`) and `--version=1` prints argparse's own error. DEFER → T01.2 rewrites __main__.py anyway (no args starts the server): no abbreviations.
Notes kept: pysbd 0.3.4 emits SyntaxWarning on first compile under 3.12 → any future `filterwarnings = error` needs a scoped ignore; pytest-timeout installed but no timeout configured → T01.2 sets timeouts on its subprocess tests; Windows non-ASCII-path editable install untested (CI paths are ASCII).
Decision: Told the owner to merge PR #6 (CI green).

### E-0049 · 2026-11-13 13:51 (Asia/Colombo) · T01.2, T02.1 · TASK-ASSIGNED
Context: With T01.1 merged, ready: T01.2, T01.6, T02.1, T03.9, T03.4 and T06.1. Recommended two in parallel now on the critical path to M1: T01.2 (RPC chain) and T02.1 (book-import chain). Offered the others when the owner wants more parallel sessions.
Decisions in the prompts (Builders record in Appendix 3):
- T01.2: no JSON-RPC batch support (the app never sends batches); a JSON array → one -32600 Invalid Request response. stdout and stdin are UTF-8 with "\n" line endings on every OS (Windows text mode would otherwise write "\r\n" and use the locale code page). Plus the T01.1 carry-overs: R1-1, R1-2, R1-3 (E-0048). The T01.1 no-arg test is replaced, since no args now starts the server.
- T02.1: fixture definitions are **TOML** read with the stdlib `tomllib`, not YAML. Why: the spec requires make_epubs.py to be standard-library only, and there is no stdlib YAML parser; TOML keeps it dependency-free and readable. Every spec mention of the "YAML" fixture definitions (C3.2, T02.1, T02.2, T02.3, T02.8) means these TOML files. Generated EPUBs use ZIP_STORED for every entry with fixed timestamps and order, so the bytes are identical on every OS and zlib build (the determinism test runs in CI on Windows and Linux). Independent-reader check: EPUBCheck (W3C, BSD-3) if a Java runtime is already available, with the jar kept in .cache/; otherwise the Builder says so and the Orchestrator arranges an owner check. Public-domain books: short, from Project Gutenberg, public domain in the US and in life+70 countries (author died before 1956, published before 1931), Gutenberg header and licence kept intact.

### E-0050 · 2026-11-13 14:29 (Asia/Colombo) · T01.1 · MERGED
Context: PR #6 merged into master as `e3327d8` (normal merge). T01.1 ticked.

### E-0051 · 2026-11-13 14:29 (Asia/Colombo) · T01.2 · REVIEW-PROMPT
Context: T01.2 handoff (Antigravity / Gemini, cloud Linux/Debian 12 with a project-local uv Python 3.12 in .cache/uv-python, pasted by the owner). PR #7 (https://github.com/Guna210/Skald/pull/7), branch `task/T01.2-jsonrpc-server`, commits 9040b29 (setuptools>=77.0.3), ba94fa7, 0b45599 on master e3327d8. +880/−11: rpc/server.py 399, rpc/__init__.py 29, __main__.py, test_rpc_server.py 415, test_imports.py, pyproject floor, SPEC tick + 3 Appendix 3 rows (libsndfile LGPL; no batches/notifications; UTF-8 + LF). 31 tests locally.
CI checked via the API: push run 43393553332 and PR run 43393579216 both success (all jobs, incl. core windows-latest), which answers the Builder's open question.
Builder decisions: SkaldError lives in rpc/server.py; argparse replaced by exact argv matching; a `setup` callback on run_stdio_server for subprocess tests; managed logging handlers tagged, RotatingFileHandler 5 MiB × 3.
Size note: ~880 lines vs size M (300–700); about half is tests.
Decision: Review by a fresh Claude Sonnet session (Builder Gemini). Focus: stdout purity and the writer under threads; UTF-8/LF on Windows (binary buffers); the test-only `setup` hook in production code (Ponytail); error mapping; carry-overs a/b/c.
