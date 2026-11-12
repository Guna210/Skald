# Orchestrator state — snapshot

Last updated: 2026-11-13 00:13 (Asia/Colombo) · last entry: E-0014
Current log file: `CONTEXT.md` (entries E-0001 onward)

## Where the project is
- Phase 0: T00.1 merged (`3e4a81d`). T00.2 in review (PR #3, round 1). T00.3 assigned, building in parallel (no handoff yet).
- `master` at `3e4a81d`. Default branch `master`; spec v1.0 approved (E-0005).
- Open PRs: PR #3 T00.2 (https://github.com/Guna210/Skald/pull/3) — in review, round 1.
- Releases/tags: none (`deps-v1` mirror comes with T00.3).
- Milestones reached: none (next: M1 after T05.8).

## Tasks
- Merged: T00.1 (PR #2).
- In review: T00.2 — round 1, Reviewer prompt issued (E-0014).
- Assigned (round 1, building): T00.3 pinned binaries [REVIEW] (E-0012).
- Next after T00.2 + T00.3: T00.4 CI skeleton. After T00.2 alone: T01.1 → then T01.x, T02.1, T03.9 in parallel.

## Waiting on the owner
1. Open a fresh Claude session (Sonnet) and paste the T00.2 Reviewer prompt (E-0014).
2. Bring the T00.3 handoff when it arrives.

## Pending GPU runs
None.

## Open questions from Builders / Reviewers
None.

## Deferred findings
- R1-1 (T00.1, Nit): docs/defaults.md C1.1 item 5 should say alt text / note bodies are skipped "by default". Fix in T02.3 (E-0011).

## Decisions not yet written into SPEC.md
- E-0012 clarifications (T00.2 `.npmrc` placement, setup.ps1 Python lookup; T00.3 unittest-style tests, ffmpeg build choice, safe extraction) — the T00.2/T00.3 Builders record them.

## Standing notes for prompts
- Builder prompts: owner authorizes pushing to `task/<ID>-<slug>` and opening a PR, even if a Claude cloud session got a `claude/…` branch (E-0004). Reviewer prompts: read-only, no pushes or PR comments.
- `<owner>` in the spec = `Guna210`.
- Handoffs and verdicts may arrive as cross-session messages; verify against the PR before acting (E-0009).
- Remind the owner to use "Squash and merge" — PR #1 and PR #2 both went in as merge commits (E-0007, E-0013).
- T00.4 prompt: CI must also run `scripts/tests` (unittest-style, from T00.3) (E-0012).
- T00.2/T00.3 run in parallel: the second to merge needs a rebase on master (E-0012).
- T02.3 prompt: include deferred R1-1 (E-0011).
- T09.2: confirm the CLEANUP.md user-data paths once productName is set (E-0009).

## Recommended next step
Wait for the T00.2 verdict and the T00.3 handoff. If T00.2 merges first, tell the T00.3 Builder to rebase on master before review/merge.
