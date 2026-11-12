# Orchestrator state — snapshot

Last updated: 2026-11-13 01:56 (Asia/Colombo) · last entry: E-0026
Current log file: `CONTEXT.md` (entries E-0001 onward)

## Where the project is
- Phase 0: T00.1, T00.2 merged. T00.3 PR #4 round 4 pushed and rebased; in its first Skald review (ROUND 4). T00.4 waits for T00.3.
- Phase 1: T01.1 prompt issued (E-0020); owner may have started it.
- `master` at `3278d73`. Default branch `master`; spec v1.0 approved (E-0005). Merge method: normal merge (E-0021).
- Open PRs: PR #4 T00.3 (https://github.com/Guna210/Skald/pull/4) — round 4 in review (E-0026).
- Releases/tags: none. `deps-v1` mirror: owner creates it after T00.3 is approved (~394 MB, 6 files) (E-0024).
- Milestones reached: none (next: M1 after T05.8).

## Tasks
- Merged: T00.1 (PR #2), T00.2 (PR #3).
- In review: T00.3 — round 4 (Reviewer prompt E-0026) (Builder tool did rounds 1–3 internally; Skald Reviewer reviews as ROUND 4, findings R4-n) (E-0023–E-0025). [REVIEW] gate part 1 done: all 6 lock-file hashes verified by the Orchestrator (E-0023).
- Assigned: T01.1 core package skeleton (E-0020).
- Next: T00.4 after T00.3. After T01.1: T01.2, T01.6, T02.1, T03.9 in parallel; T03.4 also needs T00.3.

## Waiting on the owner
1. Open a fresh Claude session (Opus) and paste the T00.3 Reviewer prompt (E-0026).
2. Start T01.1 if not yet started (E-0020).
3. After T00.3 approval: create the `deps-v1` release per docs/spikes/deps-mirror.md.

## Pending GPU runs
None.

## Open questions from Builders / Reviewers
None.

## Deferred findings
- Open item: who creates `core/requirements.lock` (B3)? Not T01.1. Decide by T04.1/T09.1 (E-0020).
- R1-1 (T00.1, Nit): docs/defaults.md C1.1 item 5 should say alt text / note bodies are skipped "by default". Fix in T02.3 (E-0011).

## Decisions not yet written into SPEC.md
- E-0024 recorded in PR #4's Appendix 3 rows (pending merge).
- E-0021 normal merge instead of squash — CLAUDE.md lines 45 and 99 still say squash; fix via the T00.4 PR (E-0025).
- E-0020 T01.1 clarifications (CI criterion timing, requirements.lock not created, no-arg behaviour) — the T01.1 Builder records them.
- E-0012 clarifications (T00.2 `.npmrc` placement, setup.ps1 Python lookup; T00.3 unittest-style tests, ffmpeg build choice, safe extraction) — the T00.2/T00.3 Builders record them.

## Standing notes for prompts
- Builder prompts: owner authorizes pushing to `task/<ID>-<slug>` and opening a PR, even if a Claude cloud session got a `claude/…` branch (E-0004). Reviewer prompts: read-only, no pushes or PR comments.
- `<owner>` in the spec = `Guna210`.
- Handoffs and verdicts may arrive as cross-session messages; verify against the PR before acting (E-0009).
- Merge method: normal merge ("Create a merge commit"), owner decision (E-0021). Never tell the owner to squash.
- T00.4 prompt: also change CLAUDE.md line 45 ("Use **Squash and merge**") and line 99 (merge steps) to the normal merge, plus an Appendix 3 row (E-0021).
- T00.4 prompt: CI must also run `scripts/tests` (unittest-style, from T00.3) (E-0012); source dev-env before any npm/pip call; watch for Windows PowerShell 5.1 + `$ErrorActionPreference=Stop` turning native stderr (pip) into errors (E-0016).
- Every Builder prompt that runs npm: source `scripts/dev-env.*` first — there is no `.npmrc` (E-0016).
- T00.2/T00.3 run in parallel: the second to merge needs a rebase on master (E-0012).
- T02.3 prompt: include deferred R1-1 (E-0011).
- T09.4: ffmpeg is LGPL-3.0-or-later (`--enable-version3`); ship the LGPL-3.0 text + source link (E-0024).
- T09.2: confirm the CLEANUP.md user-data paths once productName is set (E-0009).

## Recommended next step
T00.3 round-4 handoff → check rebase and the two changes → Reviewer prompt (fresh Opus, ROUND 4). T01.1 handoff → check base, then Reviewer prompt.
