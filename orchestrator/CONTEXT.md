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
