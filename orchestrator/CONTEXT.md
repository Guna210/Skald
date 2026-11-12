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
