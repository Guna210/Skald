# Orchestrator state — snapshot

Last updated: 2026-11-12 23:54 (Asia/Colombo) · last entry: E-0012
Current log file: `CONTEXT.md` (entries E-0001 onward)

## Where the project is
- Phase 0: T00.1 APPROVED (PR #2), waiting for the owner to squash-merge. T00.2 and T00.3 prompts issued, to be pasted after the merge.
- `master` at `db7a0d9` (PR #1). Default branch `master`; spec v1.0 approved (E-0005).
- Open PRs: PR #2 T00.1 (https://github.com/Guna210/Skald/pull/2) — APPROVED round 1, merge pending.
- Releases/tags: none (`deps-v1` mirror comes with T00.3).
- Milestones reached: none (next: M1 after T05.8).

## Tasks
- Merged: none (T00.1 approved, not merged yet).
- Assigned (round 1, not started): T00.2 dev setup scripts; T00.3 pinned binaries [REVIEW] (E-0012).
- Next after both: T00.4 CI skeleton. After T00.2 alone: T01.1 → then T01.x, T02.1, T03.9 in parallel.

## Waiting on the owner
1. Squash-merge PR #2 (no CI yet, so nothing to wait for) (E-0011).
2. Then paste the T00.2 and T00.3 prompts into two Builder sessions (E-0012).

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
- Remind the owner to use "Squash and merge" (E-0007).
- T00.4 prompt: CI must also run `scripts/tests` (unittest-style, from T00.3) (E-0012).
- T00.2/T00.3 run in parallel: the second to merge needs a rebase on master (E-0012).
- T02.3 prompt: include deferred R1-1 (E-0011).
- T09.2: confirm the CLEANUP.md user-data paths once productName is set (E-0009).

## Recommended next step
Owner merges PR #2, then runs the T00.2 and T00.3 Builders. On each handoff: verify against the PR, then issue its Reviewer prompt.
