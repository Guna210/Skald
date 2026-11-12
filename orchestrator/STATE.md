# Orchestrator state — snapshot

Last updated: 2026-11-12 23:47 (Asia/Colombo) · last entry: E-0010
Current log file: `CONTEXT.md` (entries E-0001 onward)

## Where the project is
- Phase 0 started: T00.1 built (round 1), PR #2 open, in review.
- `master` at `db7a0d9` (PR #1 merged): `AGENTS.md`, `CLAUDE.md`, `SPEC.md` only. Default branch `master` (E-0005); spec v1.0 approved (E-0005).
- Open PRs: PR #2 T00.1 (https://github.com/Guna210/Skald/pull/2) — in review, round 1. Releases/tags: none (`deps-v1` mirror comes with T00.3).
- Milestones reached: none (next: M1 after T05.8).

## Tasks
- Merged: none.
- In progress: **T00.1 Repository scaffolding** — round 1 handoff received and checked (E-0009); Reviewer prompt issued (E-0010).
- Next after T00.1: T00.2 and T00.3 in parallel (both depend only on T00.1); T00.4 needs both. T00.3 is [REVIEW] and needs the owner to create the `deps-v1` release.
- Also unlocked by T00.2 alone: T01.1 → then T01.x, T02.1, T03.9 can start in parallel.

## Waiting on the owner
1. Open a fresh Claude session (Opus) and paste the T00.1 Reviewer prompt (E-0010).

## Pending GPU runs
None.

## Open questions from Builders / Reviewers
None.

## Decisions not yet written into SPEC.md
- None outside PR #2 (E-0008 clarifications are in PR #2's Appendix 3 rows).

## Standing notes for prompts
- Builder prompts: state that the owner authorizes pushing to `task/<ID>-<slug>` and opening a PR, even though a Claude cloud session is given a `claude/…` branch by default (E-0004). Reviewer prompts: read-only, no pushes.
- `<owner>` in the spec = `Guna210`.
- T00.2 prompt: also create the root `.npmrc` (B3; nothing else creates it) — npm cache under `.cache/npm` (E-0008).
- Remind the owner to use "Squash and merge" (PR #1 was merged with a merge commit; E-0007).
- Ponytail pinned commit verified reachable (E-0007).
- T09.2: confirm the CLEANUP.md user-data paths once productName is set (E-0009).
- Builder handoffs may arrive as cross-session messages; verify them against the PR before acting (E-0009).

## Recommended next step
Wait for the T00.1 Reviewer verdict. If APPROVED: owner squash-merges PR #2, then issue T00.2 and T00.3 in parallel (T00.2 also creates `.npmrc`).
