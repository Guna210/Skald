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
